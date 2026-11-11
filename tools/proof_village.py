"""Visible scratch-world checks for the village design: regular villagers keep
their lives, and the village gains extra guards on top of them."""

import argparse
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = Path(r"D:\CGRLabs\Horizon-Ecosystem\horizon-windows-x64")
OUT = ROOT / "target" / "proof"
VILLAGER = "minecraft:villager"
SWORDS = ("minecraft:iron_sword", "minecraft:crossbow")
SWORD = "minecraft:iron_sword"
CROSSBOW = "minecraft:crossbow"
HUSK = "minecraft:husk"
MELEE_REACH = 2.5
VILLAGERS = 6
GUARDS_FOR_SIX = 4


def guards_for(regular):
    """Two guards for every three villagers, rounded up."""
    return -(-regular * 2 // 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--seconds", type=int, default=40)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-village-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-village-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "village-v06.log").open("w", encoding="utf-8")
    report = {"game": game, "scratch_home": str(home)}

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    def ctl(*a, timeout=60):
        o, e = OUT / "ctl.out", OUT / "ctl.err"
        with o.open("wb") as fo, e.open("wb") as fe:
            done = subprocess.run([args.ctl, *a], stdout=fo, stderr=fe, env=env,
                                  timeout=timeout, cwd=str(home))
        text = o.read_text(encoding="utf-8", errors="replace").strip()
        err = e.read_text(encoding="utf-8", errors="replace").strip()
        if done.returncode != 0:
            raise RuntimeError(f"ctl {' '.join(a)} -> {done.returncode}: {text or err}")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = {"_raw": text}
        if isinstance(value, dict) and "error" in value:
            raise RuntimeError(f"ctl {' '.join(a)} -> {value['error']}")
        return value

    def command(text):
        value = ctl("command", text)
        say(f"command {text}: {json.dumps(value)}")
        return value

    def wait(ticks):
        ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))

    def entities(radius=64):
        return ctl("entities", str(radius))["entities"]

    def villagers():
        return [m for m in entities() if m.get("type") == VILLAGER]

    def mobs():
        # The mobs near the player, with what they hold and wear.
        return [m for m in ctl("mobs", "64")["near"] if m.get("kind") == VILLAGER]

    def guards():
        return [m for m in mobs() if m.get("held") in SWORDS]

    def regular():
        return [m for m in mobs() if m.get("held") not in SWORDS]

    def shot(name, pos, look=None):
        x, y, z = pos
        ctl("tp", str(x), str(y), str(z + 5))
        ctl("look-at", str(x), str(y + 1.0), str(z))
        wait(8)
        path = OUT / f"village-v06-{name}.png"
        ctl("screenshot", str(path))
        say(f"screenshot {name}: {path}")

    try:
        say(f"scratch home: {home}")
        say("launching VISIBLE window...")
        ctl("launch", "--game", game, "--world", "GuardVillageV06", "--creative", "--wait",
            "--render-distance", "6", "--resources", args.resources, "--test-terrain", timeout=420)
        ctl("wait-ready", "120", timeout=150)
        ctl("options-set", "pauseOnLostFocus", "false")
        for _ in range(6):
            if ctl("state").get("screen") == "playing":
                break
            ctl("close")
            ctl("resume")
            wait(5)
        assert ctl("state").get("screen") == "playing", "game did not enter playing state"
        ctl("options-set", "tutorialStep", "none")
        ctl("key", "f1", "tap")
        command("time set day")
        command("weather clear")
        ctl("tp", "0", "90", "0")
        command("fill -24 89 -24 24 89 24 minecraft:stone")
        command("fill -24 90 -24 24 98 24 minecraft:air")
        ctl("tp", "0", "90", "0")
        wait(10)

        # A village of six villagers, standing together.
        for x in range(-5, 6, 2):
            command(f'summon {VILLAGER} {x} 90 0 {{NoAI:1b,Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",level:1}}}}')
        wait(30)

        adults = [m for m in villagers() if not m.get("baby") and m.get("health", 0) > 0]
        say(f"villagers: {len(adults)}")
        report["summoned"] = adults
        assert len(adults) >= VILLAGERS, f"the village lost villagers: {len(adults)}"

        # What the villagers were before the mod added anything: their
        # professions are the village's business, not the mod's. The control
        # API reports every mob by id with its profession index (`creatures.rs`
        # control_mobs), so this compares the same person, not whoever happens
        # to stand within two blocks of a remembered coordinate.
        before = {m["id"]: m.get("profession") for m in mobs()}
        report["professions_before"] = before

        # The guards arrive on their own.
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            wait(10)
            if len(guards()) >= guards_for(VILLAGERS):
                break
        found = guards()
        farmers = regular()
        report["guards"] = found
        report["regular"] = farmers
        want = guards_for(VILLAGERS)
        say(f"guards: {len(found)} (want {want}), villagers: {len(farmers)} (want {VILLAGERS})")
        shot("village", (0, 90, 0))
        assert len(found) == want, f"village of {VILLAGERS} got {len(found)} guards, want {want}"
        assert want == GUARDS_FOR_SIX, f"the ratio changed: {want}"
        assert len(farmers) == VILLAGERS, f"regular villagers: {len(farmers)}"
        # The village's own villagers are untouched: no weapons, and the
        # profession they had is the profession they still have.
        for mob in farmers:
            assert mob.get("held") is None, f"a regular villager was armed: {mob}"
        after = {m["id"]: m.get("profession") for m in mobs()}
        changed = {str(i): [before[i], after[i]] for i in before
                   if i in after and after[i] != before[i]}
        report["professions_changed"] = changed
        assert not changed, f"the mod changed a villager's profession: {changed}"
        report["professions_unchanged"] = True

        # The guards wear the armour: as many villagers wear the chestplate as
        # there are guards.
        text = json.dumps(command("execute as @e[type=minecraft:villager] run "
                                  "data get entity @s equipment"))
        armoured = text.count("iron_chestplate")
        report["armoured"] = armoured
        assert armoured == len(found), \
            f"{armoured} villagers wear the armour, {len(found)} guards hold a weapon"
        for mob in found:
            assert mob["held"] in SWORDS, f"a guard holds nothing: {mob}"

        shot("village", (0, 90, 0))
        guard = found[0]
        shot("guard", guard["pos"])

        # A baby born next to a guard grows up into one.
        gx, gy, gz = guard["pos"]
        command(f'summon {VILLAGER} {gx + 1} {gy} {gz} {{Age:-240,NoAI:1b,Rotation:[180f,0f],'
                f'Tags:["guard_baby"]}}')
        wait(10)
        baby = next((m for m in villagers() if m.get("baby")), None)
        assert baby is not None, "no baby appeared"
        report["baby"] = baby
        command(f'data merge entity @e[type={VILLAGER},tag=guard_baby,limit=1] {{NoAI:0b}}')
        deadline = time.monotonic() + args.seconds
        grown = None
        while time.monotonic() < deadline:
            wait(20)
            grown = next((m for m in villagers() if m["id"] == baby["id"]), None)
            if grown and not grown.get("baby"):
                break
        assert grown and not grown.get("baby"), "the baby did not grow up"
        report["grown"] = grown
        grown_held = next((m.get("held") for m in mobs() if m["id"] == grown["id"]), None)
        report["grown_held"] = grown_held
        assert grown_held in SWORDS, f"the grown villager is not a guard: {grown_held}"
        shot("grown-guard", grown["pos"])

        # Each guard on its own ground, and the only armed mob left alive in
        # the world while it fights: every other villager is killed before the
        # site is built, so the damage the husk takes can only be this guard's.
        # A village of one villager gets one guard, which is what the site has.
        command("difficulty normal")

        def nearby(radius=48):
            # The mobs around the player: kind, place, health, weapon.
            return [m for m in ctl("mobs", str(radius))["near"] if m.get("kind") == VILLAGER]

        def guards_near(radius=48):
            return [m for m in nearby(radius) if m.get("held") in SWORDS]

        def everything(radius=64):
            return ctl("mobs", str(radius))["near"]

        def a_husk(m):
            return "husk" in str(m.get("kind", "")).lower()

        def husks(radius=64):
            # Every husk the game reports, dead ones included: a killed husk
            # stays in the list for a while, so the tests track the one they
            # summoned by its id rather than by looking for a husk anywhere.
            return [m for m in everything(radius) if a_husk(m)]

        def bolts():
            # Projectiles in the air. The control API names them after the
            # server's own type (`Arrow`), so the match ignores case.
            flying = ctl("simulation").get("projectiles", []) or []
            names = sorted({str(p.get("kind", "")) for p in flying})
            return len([p for p in flying
                        if "arrow" in str(p.get("kind", "")).lower()]), names

        def goto(pos):
            # `ctl tp` moves only the client's copy of the player. The world
            # loads its chunks around the *server's* player and the mob list is
            # measured from where the game says the player stands, so a test
            # far from the arena needs the game's own command as well.
            x, y, z = pos
            command(f"tp @a {x} {y} {z}")
            ctl("tp", str(x), str(y), str(z))
            wait(30)

        def site(index):
            return 40 + 60 * index, 90, 0

        def build_site(index):
            x, y, z = site(index)
            goto((x, y, z + 6))
            # Ground wide enough for the guard to be put on, and air over it.
            command(f"fill {x - 8} {y - 1} {z - 8} {x + 12} {y - 1} {z + 8} minecraft:stone")
            command(f"fill {x - 8} {y} {z - 8} {x + 12} {y + 5} {z + 8} minecraft:air")
            command(f'summon {VILLAGER} {x} {y} {z} {{NoAI:1b,Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",'
                    f'level:1}}}}')
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                wait(10)
                found = guards_near(32)
                standing = [m for m in found if abs(m["pos"][1] - y) < 1.5
                            and m["health"] == 20.0]
                if len(standing) == 1:
                    return standing[0]
            raise RuntimeError(f"site {index} settled on {guards_near(32)}, not one guard "
                               f"standing on its own ground")

        command("kill @e[type=minecraft:villager]")
        wait(40)

        def strike(who, standoff, seconds, name):
            """Damage a husk takes with only this guard alive in the world.

            Every other villager is killed before the site is built, so the
            guard under test is the only armed mob there is, and the husk is
            summoned at its own position rather than a remembered one."""
            fresh = next((m for m in nearby(32) if m["id"] == who["id"]), None)
            assert fresh is not None, f"the {name} guard vanished before its test"
            x, y, z = fresh["pos"]
            command("kill @e[tag=proof_husk]")
            wait(10)
            # A husk is the undead that does not burn away in daylight, so it
            # lives long enough to be struck while the test watches.
            known = {m["id"] for m in husks()}
            command(f'summon {HUSK} {int(round(x + standoff))} {int(round(y))} {int(round(z))} '
                    f'{{NoAI:1b,PersistenceRequired:1b,Tags:["proof_husk"]}}')

            def mine():
                fresh_husks = [m for m in husks() if m["id"] not in known]
                return fresh_husks[0] if fresh_husks else None

            deadline = time.monotonic() + args.seconds
            target = None
            while time.monotonic() < deadline and target is None:
                target = mine()
                if target is None:
                    wait(5)
            assert target is not None, (
                f"no husk for the {name} test; the guard stood at "
                f"{[round(v, 1) for v in fresh['pos']]}, mobs seen: "
                f"{sorted({str(m.get('kind')) for m in everything(64)})}")
            assert target["health"] == 20.0, f"the husk was hurt before the {name} test: {target}"
            first = None
            since = None
            arrows = 0
            seen = set()
            goals_seen = set()
            targets_seen = set()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                wait(2)
                alive = next((m for m in nearby(32) if m["id"] == who["id"]), None)
                assert alive is not None and alive["health"] > 0, f"the {name} guard died"
                goals_seen.update(alive.get("goals") or [])
                if alive.get("target") is not None:
                    targets_seen.add(str(alive["target"]))
                count, names = bolts()
                arrows = max(arrows, count)
                seen.update(names)
                now = mine()
                if now is None:
                    # The husk left the world: the guard killed it, which is
                    # the strongest thing this fight can show.
                    assert first is not None, f"the husk vanished before the {name} hit"
                    break
                if now["health"] < target["health"] and first is None:
                    first, since = (now, alive), time.monotonic()
                elif since is not None:
                    # Keep watching for a few seconds: the goal the mod gave
                    # the guard only reads as running in some ticks, so the
                    # sample above gathers it while the fight goes on. The
                    # attribution below stays with the first hit, before
                    # knockback moved anyone.
                    if time.monotonic() - since > 4.0:
                        break
            assert first is not None, (
                f"the {name} guard dealt no damage in {seconds}s; in the air: {sorted(seen)}")
            hit, struck = first
            # Nobody else was armed anywhere, so this damage is the guard's.
            others = [m for m in guards_near(200) if m["id"] != who["id"]]
            assert not others, f"another guard was alive for the {name} test: {others}"
            own = math.dist(hit["pos"], struck["pos"])
            # The goal the mod put on the guard, seen running at some point in
            # the fight. A bolt only lives a few ticks in the air and a goal
            # reads as running only in the ticks it is starting or holding, so
            # this is gathered over the whole fight rather than one poll. The
            # point stands on the goal, the distance and the fact that no other
            # armed mob existed: a vanilla villager runs neither goal.
            want_goal = "CrossbowAttack" if name == "crossbow" else "MeleeAttack"
            assert want_goal in goals_seen, \
                f"the {name} guard never ran its {want_goal}: {sorted(goals_seen)}"
            if name == "crossbow":
                assert own > MELEE_REACH, f"the archer shot from melee reach: {own}"
            else:
                assert own <= MELEE_REACH + 1.5, \
                    f"the sword guard struck from {own:.1f} blocks, past its reach"
            kept = next((m for m in nearby(32) if m["id"] == who["id"]), None)
            assert kept.get("held") == who["held"], f"the {name} guard lost its weapon: {kept}"
            ctl("look-at-entity", str(who["id"]))
            wait(6)
            path = OUT / f"village-v06-{name}-combat.png"
            ctl("screenshot", str(path))
            result = {"guard": kept, "husk_before": {k: target[k] for k in
                                                     ("id", "kind", "pos", "health")},
                      "husk_after": {k: hit[k] for k in ("id", "kind", "pos", "health")},
                      "damage": target["health"] - hit["health"], "shot": str(path),
                      "at_hit": {"goals": sorted(goals_seen),
                                 "targets": sorted(targets_seen),
                                 "pos": struck["pos"]},
                      "arrows_seen": arrows, "projectiles_seen": sorted(seen),
                      "other_guards_alive": len(others), "guard_to_target": own,
                      "husk_burning": hit.get("burning"), "site": list(site(index))}
            say(f"{name}: {result['damage']} damage at {own:.1f} blocks with only "
                f"{want_goal} running and no other guard alive — {path}")
            return result

        report["sites"] = {}
        want = {SWORD: ("melee", 1.0, 25), CROSSBOW: ("crossbow", 6.0, args.seconds)}
        proved = {}
        for index in range(5):
            command("kill @e[type=minecraft:villager]")
            wait(40)
            guard = build_site(index)
            report["sites"][str(index)] = guard
            say(f"site {index}: one villager, one guard holding {guard['held']} at "
                f"{[round(v, 1) for v in guard['pos']]}")
            if guard["held"] in want and guard["held"] not in proved:
                name, standoff, seconds = want[guard["held"]]
                proved[guard["held"]] = strike(guard, standoff, seconds, name)
            if len(proved) == len(want):
                break
        assert len(proved) == len(want), f"only proved {sorted(proved)} of {sorted(want)}"
        report["melee_combat"] = proved[SWORD]
        report["crossbow_combat"] = proved[CROSSBOW]

        # Back at the arena: the village is built again from scratch and the
        # mod works out on its own that it needs guards, with nobody of its own
        # people touched. This is what the release screenshot shows.
        goto((0, 90, 5))
        command("kill @e[type=minecraft:villager]")
        wait(40)
        for x in range(-5, 6, 2):
            command(f'summon {VILLAGER} {x} 90 0 {{NoAI:1b,Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",'
                    f'level:1}}}}')
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            wait(10)
            if len(guards()) >= guards_for(VILLAGERS):
                break
        farmers = [m for m in regular() if not m.get("baby")]
        report["rebuilt"] = {"villagers": len(farmers), "guards": len(guards())}
        say(f"the rebuilt village: {len(farmers)} villagers, {len(guards())} guards")
        assert len(farmers) == VILLAGERS, f"the rebuilt village kept {len(farmers)} villagers"
        assert len(guards()) == guards_for(VILLAGERS), \
            f"the rebuilt village raised {len(guards())} guards"
        assert all(m.get("held") is None for m in farmers), "a rebuilt villager was armed"
        shot("after-combat", (0, 90, 0))

        report["passed"] = True
        say(f"village of {VILLAGERS} villagers: {len(found)} guards added, farmers untouched, "
            "the guard's baby grew into a guard, melee and crossbow damage observed")
    except Exception as exc:
        report["error"] = str(exc)
        say(f"FAILED: {exc}")
        raise
    finally:
        (OUT / "village-v06-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
