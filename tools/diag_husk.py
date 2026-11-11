"""Where does a summoned husk go?

Summons the target at the main arena and far down the X axis, and prints every
mob the game reports, its place, health and whether it burns. Reads only: the
answer decides how the village proof observes combat.
"""

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-husk-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-husk-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"

    def ctl(*a, timeout=90):
        o, e = OUT / "d-ctl.out", OUT / "d-ctl.err"
        with o.open("wb") as fo, e.open("wb") as fe:
            done = subprocess.run([args.ctl, *a], stdout=fo, stderr=fe, env=env,
                                  timeout=timeout, cwd=str(home))
        text = o.read_text(encoding="utf-8", errors="replace").strip()
        err = e.read_text(encoding="utf-8", errors="replace").strip()
        if done.returncode != 0:
            raise RuntimeError(f"ctl {' '.join(a)} -> {done.returncode}: {text or err}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}

    def say(msg):
        print(msg, flush=True)

    def command(text):
        say(f">> command {text}: {json.dumps(ctl('command', text))}")

    def wait(ticks):
        ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))

    def short(m):
        return {"id": m.get("id"), "kind": m.get("kind"),
                "pos": [round(float(v), 1) for v in m.get("pos", [])],
                "health": m.get("health"), "burning": m.get("burning"),
                "on_ground": m.get("on_ground"), "goals": m.get("goals")}

    def look(tag, radius=64):
        near = ctl("mobs", str(radius))["near"]
        say(f"{tag}: mobs {radius} -> " + json.dumps([short(m) for m in near]))
        ents = ctl("entities", str(radius))["entities"]
        say(f"{tag}: entities {radius} -> " + json.dumps(
            [{"id": e.get("id"), "type": e.get("type"),
              "pos": [round(float(v), 1) for v in e.get("pos", [])]} for e in ents]))
        sim = ctl("simulation")
        say(f"{tag}: game_time {sim.get('game_time')} projectiles "
            + json.dumps(sim.get("projectiles", [])))

    try:
        say(f"scratch home: {home}")
        ctl("launch", "--game", game, "--world", "GuardHuskDiag", "--creative", "--wait",
            "--render-distance", "6", "--resources", args.resources, "--test-terrain", timeout=420)
        ctl("wait-ready", "120", timeout=150)
        ctl("options-set", "pauseOnLostFocus", "false")
        for _ in range(6):
            if ctl("state").get("screen") == "playing":
                break
            ctl("close")
            ctl("resume")
            wait(5)
        ctl("tp", "0", "90", "0")
        command("fill -24 89 -24 24 89 24 minecraft:stone")
        command("fill -24 90 -24 24 98 24 minecraft:air")
        command("time set day")
        command("weather clear")
        command("difficulty normal")
        wait(20)

        for x in (0, 160):
            if x:
                ctl("tp", str(x), "90", "4")
                command(f"fill {x - 3} {89} -3 {x + 6} 89 3 minecraft:stone")
                command(f"fill {x - 3} 90 -3 {x + 6} 96 3 minecraft:air")
                wait(20)
            command(f'summon {VILLAGER} {x} 90 0 {{NoAI:1b,Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",'
                    f'level:1}}}}')
            command(f'summon minecraft:husk {x + 1} 90 0 '
                    f'{{NoAI:1b,PersistenceRequired:1b,Tags:["diag_husk"]}}')
            command(f'summon minecraft:zombie {x + 2} 90 0 '
                    f'{{NoAI:1b,PersistenceRequired:1b,Tags:["diag_zombie"]}}')
            wait(10)
            look(f"x{x} +10 ticks")
            wait(40)
            look(f"x{x} +50 ticks")
            wait(100)
            look(f"x{x} +150 ticks")
            command("kill @e[tag=diag_husk]")
            command("kill @e[tag=diag_zombie]")
            command("kill @e[type=minecraft:villager]")
            wait(20)

        look("final", radius=200)
        say("done")
    finally:
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")


if __name__ == "__main__":
    main()
