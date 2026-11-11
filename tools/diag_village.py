"""Diagnostic: what does the server think of the guards the mod adds?"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = Path(r"D:\CGRLabs\Horizon-Ecosystem\horizon-windows-x64")
OUT = ROOT / "target" / "proof"
OUT.mkdir(parents=True, exist_ok=True)
GAME = ROOT / "target" / "horizon-cargo" / "fast" / "horizon-client.exe"

env = dict(os.environ)
home = Path(tempfile.mkdtemp(prefix="guard-diag-home-"))
env["HORIZON_HOME"] = str(home)
env["HORIZON_CONTROL"] = str(home / "control.sock")
for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
    env[key] = tempfile.mkdtemp(prefix="guard-diag-")
env["HORIZON_NO_AUDIO"] = "1"


def ctl(*a, timeout=90):
    o, e = OUT / "d.out", OUT / "d.err"
    with o.open("wb") as fo, e.open("wb") as fe:
        done = subprocess.run([str(INSTALL / "horizon-ctl.exe"), *a], stdout=fo, stderr=fe,
                              env=env, timeout=timeout, cwd=str(home))
    text = o.read_text(encoding="utf-8", errors="replace").strip()
    if done.returncode != 0:
        raise RuntimeError(f"ctl {a} -> {done.returncode}: {text}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


def command(text):
    value = ctl("command", text)
    print(f"command {text}: {json.dumps(value)}", flush=True)
    return value


print(f"scratch home: {home}", flush=True)
ctl("launch", "--game", str(GAME), "--world", "GuardDiag", "--creative", "--wait",
    "--render-distance", "6", "--resources", str(INSTALL / ".local" / "horizon-client" / "26.3"),
    "--test-terrain", timeout=420)
ctl("wait-ready", "120", timeout=150)
ctl("options-set", "pauseOnLostFocus", "false")
for _ in range(6):
    if ctl("state").get("screen") == "playing":
        break
    ctl("close")
    ctl("resume")
    ctl("wait", "5")
ctl("command", "time set day")
ctl("command", "fill -24 89 -24 24 89 24 minecraft:stone")
ctl("tp", "0", "90", "0")
for x in range(-3, 4, 2):
    command(f"summon minecraft:villager {x} 90 0 {{NoAI:1b,VillagerData:{{type:\"minecraft:plains\",profession:\"minecraft:farmer\"}}}}")
ctl("wait", "60", timeout=90)

print("\n=== client entities (villagers) ===")
for m in ctl("entities", "64")["entities"]:
    if m.get("type") == "minecraft:villager":
        print(f"  id={m['id']} held={m.get('held')!r} head={m.get('head')!r} baby={m.get('baby')}")

print("\n=== ctl mobs (near) ===")
near = ctl("mobs", "64").get("near", [])
for m in near:
    if m.get("type") == "minecraft:villager":
        print(f"  id={m['id']} held={m.get('held')!r} head={m.get('head')!r} target={m.get('target')!r}")

print("\n=== server NBT: equipment of each villager ===")
command("execute as @e[type=minecraft:villager] run data get entity @s PersistenceRequired")
command("execute as @e[type=minecraft:villager] run data get entity @s equipment")
command("execute as @e[type=minecraft:villager] run data get entity @s Brain")
command("execute as @e[type=minecraft:villager] run data get entity @s CustomName")

try:
    ctl("quit", timeout=90)
except Exception as exc:
    print(f"quit: {exc}")
