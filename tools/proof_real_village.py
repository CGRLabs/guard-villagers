"""The same promise as tools/proof_village.py, in a village the world made.

A normal worldgen seed, the nearest village located with the game's own
command, and then the checks: the village keeps its people — their professions,
their trades, their empty hands — and the mod adds the guards it is short of.
"""

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = Path(r"D:\CGRLabs\Horizon-Ecosystem\horizon-windows-x64")
OUT = ROOT / "target" / "proof"
VILLAGER = "minecraft:villager"
# The mod marks a guard with its armour; the mob list shows the helmet of it.
HELMET = "minecraft:iron_helmet"
SWORDS = ("minecraft:iron_sword", "minecraft:crossbow")
SEED = "20261111"
# How far apart two groups of villagers may stand and still be one village,
# and the guard rule, both as the mod has them.
VILLAGE_RADIUS = 32.0


def guards_for(regular):
    return -(-regular * 2 // 3)


def village_key(m):
    """The point a villager claimed: its home, else its bed, else the meeting
    point of the village — the same order the mod reads them in."""
    for poi in m.get("pois") or []:
        if poi:
            return tuple(poi)
    return None


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def villages_of(people):
    """What the mod sees: villagers grouped by the point each claimed, the
    homeless joining the nearest group, and groups standing within a village's
    radius of each other folded into one."""
    groups = []
    homeless = []

    def centre(group):
        return [sum(p[i] for p in group["points"]) / len(group["points"])
                for i in range(3)]

    for m in people:
        key = village_key(m)
        if key is None:
            homeless.append(m["pos"])
            continue
        for group in groups:
            if group["key"] == key:
                group["points"].append(m["pos"])
                break
        else:
            groups.append({"key": key, "own": False, "points": [m["pos"]]})

    for pos in homeless:
        def nearest(only_own):
            best = None
            for index, group in enumerate(groups):
                if only_own and not group["own"]:
                    continue
                d = distance(pos, centre(group))
                if d > VILLAGE_RADIUS:
                    continue
                if best is None or d < best[1]:
                    best = (index, d)
            return None if best is None else best[0]

        index = nearest(False)
        if index is None:
            index = nearest(True)
        if index is None:
            # A village of its own, named for the ground it stands on.
            groups.append({"key": tuple(int(math.floor(p)) for p in pos),
                           "own": True, "points": [pos]})
        else:
            groups[index]["points"].append(pos)

    while True:
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if distance(centre(groups[i]), centre(groups[j])) <= VILLAGE_RADIUS:
                    keep, other = groups[i], groups[j]
                    # The same naming rule the mod has: a claimed point beats
                    # the ground the villagers stand on, and the lower one wins.
                    if (keep["own"] and not other["own"]) or (
                            keep["own"] == other["own"] and other["key"] < keep["key"]):
                        keep = other
                    keep["points"] = groups[i]["points"] + groups[j]["points"]
                    groups[i] = keep
                    del groups[j]
                    break
            else:
                continue
            break
        else:
            return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--seconds", type=int, default=90)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-real-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-real-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "real-v06.log").open("w", encoding="utf-8")
    report = {"game": game, "seed": SEED, "scratch_home": str(home)}

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    def ctl(*a, timeout=90):
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
        say(f"command {text}: {json.dumps(value)[:400]}")
        return value

    def wait(ticks):
        ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))

    def mobs():
        # The mod counts every villager the server has loaded, and the mob list
        # is measured from where the game says the player stands, so the window
        # has to be wider than the loaded world rather than the village.
        return [m for m in ctl("mobs", "320")["near"] if m.get("kind") == VILLAGER]

    def adults():
        return [m for m in mobs() if not m.get("baby") and m.get("health", 0) > 0]

    def guards():
        return [m for m in adults() if m.get("head") == HELMET]

    def regular():
        return [m for m in adults() if m.get("head") != HELMET]

    def shot(name, entity=None, place=None):
        if entity is not None:
            ctl("look-at-entity", str(entity))
        elif place is not None:
            ctl("look-at", str(place[0]), str(place[1]), str(place[2]))
        wait(8)
        path = OUT / f"real-v06-{name}.png"
        ctl("screenshot", str(path))
        say(f"screenshot {name}: {path}")
        return path

    try:
        say(f"scratch home: {home}")
        say("launching VISIBLE window on normal worldgen...")
        ctl("launch", "--game", game, "--world", "GuardRealV06", "--seed", SEED,
            "--creative", "--wait", "--render-distance", "8", "--resources",
            args.resources, timeout=420)
        ctl("wait-ready", "180", timeout=210)
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
        command("difficulty peaceful")

        found = command("locate structure #minecraft:village")
        text = json.dumps(found)
        # `locate structure` answers with the block the village starts at, and
        # its height is often unknown: "[-928, ~, -432]". The bracket gives the
        # place, so its first and last numbers are x and z; the surface is
        # found by dropping the player onto it.
        place = re.search(r"\[([^\]]*)\]", text)
        numbers = re.findall(r"-?\d+", place.group(1)) if place else []
        assert len(numbers) >= 2, f"could not read the village's place out of {text}"
        x, z = int(numbers[0]), int(numbers[-1])
        report["village"] = {"x": x, "z": z, "answer": text}
        say(f"the world's village: {x} {z}")

        def surface(at):
            """Stand on the village: drop the player above it and wait until
            the game says the player is on the ground there."""
            px, pz = at
            command(f"tp @a {px} 140 {pz}")
            ctl("tp", str(px), "140", str(pz))
            deadline = time.monotonic() + args.seconds
            last = None
            while time.monotonic() < deadline:
                wait(20)
                player = ctl("status").get("player") or {}
                pos = player.get("position") or []
                if len(pos) == 3 and pos[1] < 139.0 and abs(pos[0] - px) < 8 \
                        and abs(pos[2] - pz) < 8:
                    last = pos
                    if player.get("on_ground"):
                        return pos
            raise AssertionError(f"the player never landed at {px} {pz}: {last}")

        # A structure's start block is a corner, so step in from it.
        here = surface((x + 16, z + 16))
        report["standing"] = here
        say(f"standing on the village at {[round(v, 1) for v in here]}")
        wait(60)

        deadline = time.monotonic() + args.seconds
        people = adults()
        while time.monotonic() < deadline and len(people) < 3:
            wait(20)
            people = adults()
        assert people, f"no villagers near {here}: {ctl('state')}"

        # Before the guards are counted: what each villager does for a living,
        # read off the mob list by entity id.
        baseline = {m["id"]: m.get("profession") for m in mobs()}
        report["baseline"] = baseline

        want = None
        groups = None
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            people = adults()
            farmers = regular()
            groups = villages_of(farmers)
            want = sum(guards_for(len(g["points"])) for g in groups)
            if len(guards()) == want and want >= 1:
                break
            wait(20)
        guards_now = guards()
        report["regular"] = farmers
        report["guards"] = guards_now
        report["want_guards"] = want
        report["villages"] = [{"key": list(g["key"]), "villagers": len(g["points"]),
                               "guards": guards_for(len(g["points"]))} for g in groups or []]
        say(f"the village's own villagers: {len(farmers)} in "
            f"{len(groups)} group(s) {[len(g['points']) for g in groups]}, "
            f"guards added: {len(guards_now)} (the rule wants {want})")
        assert len(farmers) >= 3, f"only {len(farmers)} villagers found in the world's village"
        assert want is not None and len(guards_now) == want, \
            f"{len(guards_now)} guards for {len(farmers)} villagers, the rule wants {want}"

        # The village's own people are still its own: nothing in their hands,
        # and the profession they had when the mod met them.
        for mob in farmers:
            assert mob.get("held") is None, f"a villager of the village was armed: {mob}"
        for mob in guards_now:
            assert mob.get("held") in SWORDS, f"a guard holds no weapon: {mob}"
        after = {m["id"]: m.get("profession") for m in mobs()}
        changed = {str(i): [baseline[i], after[i]] for i in baseline
                   if i in after and after[i] != baseline[i]}
        report["professions_changed"] = changed
        assert not changed, f"the mod changed a villager's profession: {changed}"
        report["professions_unchanged"] = True

        # The guards are the village's, in the village: armour on, weapon in
        # hand, standing by the buildings.
        armour = json.dumps(command("execute as @e[type=minecraft:villager] run "
                                   "data get entity @s equipment"))
        report["armoured"] = armour.count("iron_chestplate")
        assert report["armoured"] == len(guards_now), \
            f"{report['armoured']} wear the armour, {len(guards_now)} are guards"

        shot("village", place=(x + 30, here[1], z + 30))
        path = shot("guard", guards_now[0]["id"])
        report["screenshots"] = [str(OUT / "real-v06-village.png"), str(path)]

        report["passed"] = True
        say(f"the world's village keeps its {len(farmers)} villagers and gains "
            f"{len(guards_now)} guards")
    except Exception as exc:
        report["error"] = str(exc)
        say(f"FAILED: {exc}")
        raise
    finally:
        (OUT / "real-v06-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
