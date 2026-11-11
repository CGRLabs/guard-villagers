"""Visible scratch-world checks for custom-skinned guards, loadouts and crossbow combat."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = Path(r"D:\CGRLabs\Horizon-Ecosystem\horizon-windows-x64")
OUT = ROOT / "target" / "proof"
VILLAGER = "minecraft:villager"
SKIN_NAMES = ("guard-villager", "guard-villager-i", "villager-guard-ii", "villager-archer")


def skin_index(mob_id):
    if mob_id % 3 == 0:
        return 3
    return (mob_id // 3 + mob_id % 3 - 1) % 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--seconds", type=int, default=35)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-gear-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-gear-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "gear-v05.log").open("w", encoding="utf-8")
    report = {"game": str(Path(args.game).resolve()), "scratch_home": str(home)}

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

    def entities():
        return ctl("entities", "64")["entities"]

    def villagers():
        return [m for m in entities() if m.get("type") == VILLAGER]

    def shot(name, mob, back=False):
        current = next(m for m in villagers() if m["id"] == mob["id"])
        x, y, z = current["pos"]
        side = 3.3 if back else -3.3
        ctl("tp", str(x), str(y), str(z + side))
        ctl("look-at", str(x), str(y + (0.55 if current.get("baby") else 1.0)), str(z))
        wait(8)
        path = OUT / f"gear-v05-{name}.png"
        ctl("screenshot", str(path))
        say(f"screenshot {name}: {path}")
        if name == "sword-shield":
            ctl("tp", str(x - 2.4), str(y), str(z - 2.4))
            ctl("look-at", str(x), str(y + 1.0), str(z))
            wait(8)
            ctl("screenshot", str(OUT / "gear-v05-sword-shield-angle.png"))

    try:
        say(f"scratch home: {home}")
        say("launching VISIBLE window...")
        ctl("launch", "--game", args.game, "--world", "GuardGearV05", "--creative", "--wait",
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
        command("difficulty peaceful")
        ctl("tp", "0", "90", "0")
        command("fill -18 89 -18 18 89 22 minecraft:stone")
        command("fill -18 90 -18 18 98 22 minecraft:air")
        ctl("tp", "0", "90", "0")
        wait(10)

        for x in range(-12, 13, 3):
            command(f'summon {VILLAGER} {x} 90 6 {{NoAI:1b,Rotation:[180f,0f],VillagerData:{{type:"minecraft:plains",profession:"minecraft:none",level:1}}}}')
        wait(20)
        adults = villagers()
        roles = {0: "crossbow", 1: "sword-shield", 2: "sword"}
        selected = {roles[m["id"] % 3]: m for m in adults if not m.get("baby")}
        assert set(selected) == set(roles.values()), f"missing loadouts: {selected}"
        assert all(m["health"] == 20.0 for m in selected.values()), "fixture took damage"
        report["adults"] = selected
        server_mobs = {m["id"]: m for m in ctl("mobs", "64")["near"]}
        report["equipment"] = {}
        for name, mob in selected.items():
            expected = "minecraft:crossbow" if name == "crossbow" else "minecraft:iron_sword"
            assert server_mobs[mob["id"]]["held"] == expected, server_mobs[mob["id"]]
            shot(name, mob)
            x, y, z = mob["pos"]
            equipment = command(f"data get entity @e[type={VILLAGER},x={x},y={y},z={z},distance=..1,limit=1] equipment")
            text = json.dumps(equipment)
            assert expected in text, equipment
            assert ("minecraft:shield" in text) == (name == "sword-shield"), equipment
            report["equipment"][name] = equipment

        skins = {}
        for m in adults:
            skins.setdefault(skin_index(m["id"]), m)
        assert set(skins) == set(range(4)), f"missing skin variants: {sorted(skins)}"
        report["skins"] = {SKIN_NAMES[i]: m["id"] for i, m in skins.items()}
        for i, mob in sorted(skins.items()):
            shot(f"skin-{SKIN_NAMES[i]}", mob)
            shot(f"skin-{SKIN_NAMES[i]}-back", mob, back=True)

        old_ids = {m["id"] for m in villagers()}
        command(f'summon {VILLAGER} 15 90 6 {{NoAI:1b,Rotation:[180f,0f],VillagerData:{{type:"minecraft:desert",profession:"minecraft:librarian",level:3}}}}')
        wait(15)
        profession = next(m for m in villagers() if m["id"] not in old_ids)
        report["profession"] = profession
        assert profession.get("villager", {}).get("type") == "desert", profession
        assert profession["villager"]["profession"] == "librarian", profession
        shot("desert-librarian", profession)

        command(f'summon {VILLAGER} 0 90 10 {{Age:-240,NoAI:1b,Rotation:[180f,0f],Tags:["guard_baby"]}}')
        wait(5)
        baby = next(m for m in villagers() if m.get("baby"))
        report["baby_before"] = baby
        server_baby = next(m for m in ctl("mobs", "64")["near"] if m["id"] == baby["id"])
        assert server_baby["held"] is None and server_baby["head"] is None, server_baby
        shot("baby", baby)
        command(f'data merge entity @e[type={VILLAGER},tag=guard_baby,limit=1] {{NoAI:0b}}')
        deadline = time.monotonic() + args.seconds
        grown = baby
        while time.monotonic() < deadline:
            wait(20)
            grown = next(m for m in villagers() if m["id"] == baby["id"])
            if not grown.get("baby"):
                break
        assert not grown.get("baby"), "baby did not reach adulthood"
        report["grown"] = grown
        server_grown = next(m for m in ctl("mobs", "64")["near"] if m["id"] == baby["id"])
        expected = "minecraft:crossbow" if baby["id"] % 3 == 0 else "minecraft:iron_sword"
        assert server_grown["held"] == expected, server_grown
        command(f'data merge entity @e[type={VILLAGER},tag=guard_baby,limit=1] {{NoAI:1b,Rotation:[180f,0f]}}')
        wait(8)
        shot("grown", grown)

        command(f"kill @e[type={VILLAGER}]")
        wait(25)
        command("difficulty normal")
        archer = None
        for _ in range(6):
            command(f"summon {VILLAGER} 0 90 0")
            wait(10)
            live = [m for m in villagers() if m.get("health", 0) > 0]
            assert len(live) == 1, f"crossbow test must isolate one guard: {live}"
            if live[0]["id"] % 3 == 0:
                archer = live[0]
                break
            command(f"kill @e[type={VILLAGER}]")
            wait(25)
        assert archer is not None, "could not isolate a crossbow guard"
        server_archer = next(m for m in ctl("mobs", "64")["near"] if m["id"] == archer["id"])
        assert server_archer["held"] == "minecraft:crossbow", server_archer
        ctl("tp", "4", "90", "3")
        command("summon minecraft:husk 0 90 8 {NoAI:1b,PersistenceRequired:1b}")
        wait(2)
        husk = next(m for m in entities() if m.get("type") == "minecraft:husk")
        assert husk["health"] == 20.0, "husk was damaged before ranged test"
        report["crossbow_guard"] = archer
        report["target_before"] = husk
        samples = []
        deadline = time.monotonic() + args.seconds
        ctl("look-at-entity", str(archer["id"]))
        while time.monotonic() < deadline:
            wait(6)
            current = entities()
            target = next((m for m in current if m["id"] == husk["id"]), None)
            guard = next((m for m in current if m["id"] == archer["id"]), None)
            assert target is not None, "target disappeared before a damage sample"
            assert guard is not None and guard["health"] > 0, "crossbow guard died"
            server_mobs = ctl("mobs", "64")
            server_guard = next(m for m in server_mobs["near"] if m["id"] == archer["id"])
            assert server_guard["held"] == "minecraft:crossbow", "guard lost its crossbow"
            samples.append({"guard": guard, "target": target,
                            "server_mobs": server_mobs,
                            "projectiles": ctl("simulation").get("projectiles", [])})
            if len(samples) == 4:
                ctl("screenshot", str(OUT / "gear-v05-crossbow-combat.png"))
            if target["health"] < husk["health"]:
                report["target_after"] = target
                report["crossbow_damage"] = husk["health"] - target["health"]
                ctl("screenshot", str(OUT / "gear-v05-crossbow-hit.png"))
                break
        report["combat_samples"] = samples
        assert report.get("crossbow_damage", 0) > 0, "crossbow dealt no observed damage"
        command("kill @e[type=minecraft:husk]")
        wait(60)
        idle = next(m for m in ctl("mobs", "64")["near"] if m["id"] == archer["id"])
        assert idle["target"] is None, "guard did not leave combat after target died"
        assert idle["held"] == "minecraft:crossbow", "idle behavior removed the crossbow"
        report["after_combat"] = idle
        shot("idle-crossbow", archer)

        command(f"kill @e[type={VILLAGER}]")
        wait(25)
        melee = None
        for _ in range(6):
            command(f"summon {VILLAGER} 0 90 0")
            wait(8)
            live = [m for m in villagers() if m.get("health", 0) > 0]
            assert len(live) == 1, live
            if live[0]["id"] % 3 != 0:
                melee = live[0]
                break
            command(f"kill @e[type={VILLAGER}]")
            wait(25)
        assert melee is not None, "could not isolate a melee guard"
        x, y, z = melee["pos"]
        command(f"summon minecraft:husk {x + 1} {y} {z} {{NoAI:1b,PersistenceRequired:1b}}")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            wait(5)
            target = next((m for m in entities() if m.get("type") == "minecraft:husk"), None)
            if target is not None and target["health"] < 20:
                report["melee_damage"] = 20 - target["health"]
                break
        assert report.get("melee_damage", 0) > 0, "melee guard dealt no observed damage"
        report["passed"] = True
        say(f"crossbow damage: {report['crossbow_damage']}; melee damage: {report['melee_damage']}")
        say("loadouts, skins, profession, baby growth, ranged damage, combat exit and melee checks passed")
    except Exception as exc:
        report["error"] = str(exc)
        say(f"FAILED: {exc}")
        raise
    finally:
        (OUT / "gear-v05-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
