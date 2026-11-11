"""Short visible diagnostic run for Guard Villagers.

Launches the patched client in a REAL window, summons a villager + zombie
adjacent, samples their positions/health for ~20 s, and leaves the mod's own
hook.log (target/proof/hook.log) as the ground truth for whether the strike
hook fires and what it sees. Resilient to pauses (soft waits).

Usage: python proof_diag.py --game <patched horizon-client.exe> [--seconds 24]
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
OUT.mkdir(parents=True, exist_ok=True)

ZOMBIE = "minecraft:zombie"
VILLAGER = "minecraft:villager"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--seconds", type=int, default=24)
    args = ap.parse_args()

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-diag-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    env["HORIZON_LAUNCHER_HOME"] = tempfile.mkdtemp(prefix="guard-diag-launcher-")
    env["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="guard-diag-data-")
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="guard-diag-config-")
    env["HORIZON_NO_AUDIO"] = "1"

    log = (OUT / "diag.log").open("w", encoding="utf-8")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    def ctl(*a, timeout=60):
        o, e = OUT / "ctl.out", OUT / "ctl.err"
        with o.open("wb") as fo, e.open("wb") as fe:
            done = subprocess.run([args.ctl, *a], stdout=fo, stderr=fe, env=env,
                                  timeout=timeout, cwd=str(INSTALL))
        text = o.read_text(encoding="utf-8", errors="replace").strip()
        err = e.read_text(encoding="utf-8", errors="replace").strip()
        if done.returncode != 0:
            raise RuntimeError(f"ctl {' '.join(map(str, a))} -> {done.returncode}: {text or err}")
        return text

    def j(*a, timeout=60):
        t = ctl(*a, timeout=timeout)
        try:
            v = json.loads(t)
        except json.JSONDecodeError:
            return {"_raw": t}
        if isinstance(v, dict) and "error" in v:
            raise RuntimeError(f"ctl {' '.join(map(str, a))} -> {v['error']}")
        return v

    def soft(label, fn):
        try:
            return fn()
        except Exception as exc:
            say(f"  ! {label}: {exc}")
            return None

    def mobs(radius=48):
        v = soft("entities", lambda: j("entities", str(radius)))
        if isinstance(v, dict):
            lst = v.get("entities")
            if isinstance(lst, list):
                return [m for m in lst if isinstance(m, dict) and m.get("kind") == "mob"]
        return []

    def first(ty):
        for m in mobs():
            if m.get("type") == ty:
                return m
        return None

    say(f"scratch home: {home}")
    say("launching VISIBLE window...")
    ctl("launch", "--game", args.game, "--world", "GuardDiag", "--creative", "--wait",
        "--render-distance", "6", "--resources", args.resources, timeout=420)
    say("launch ok")

    try:
        soft("wait-ready", lambda: j("wait-ready", "120", timeout=150))
        soft("options-set pauseOnLostFocus", lambda: j("options-set", "pauseOnLostFocus", "false"))
        for _ in range(6):
            st = soft("state", lambda: j("state"))
            if isinstance(st, dict) and st.get("screen") == "playing":
                break
            soft("close", lambda: j("close"))
            soft("resume", lambda: j("resume"))
            soft("wait", lambda: j("wait", "10", timeout=20))

        soft("summon villager", lambda: j("summon", VILLAGER))
        soft("wait", lambda: j("wait", "20", timeout=30))
        guard = first(VILLAGER)
        say(f"guard: {json.dumps(guard)}")
        if guard:
            p = guard["pos"]
            soft("summon zombie", lambda: j("summon", ZOMBIE, f"{p[0]+1.0:.2f}", f"{p[1]:.2f}", f"{p[2]:.2f}"))
        else:
            soft("summon zombie", lambda: j("summon", ZOMBIE))
        soft("wait", lambda: j("wait", "5", timeout=20))
        z = first(ZOMBIE)
        if z:
            soft("frame", lambda: j("look-at-entity", str(z["id"]), "--over", "0.4"))

        deadline = time.time() + args.seconds
        i = 0
        while time.time() < deadline:
            soft("wait", lambda: j("wait", "20", timeout=25))
            g = first(VILLAGER)
            z = first(ZOMBIE)
            say(f"t{i}: guard={json.dumps(g)} zombie={json.dumps(z)}")
            if i == 3:
                soft("screenshot", lambda: j("screenshot", str(OUT / "diag.png")))
            i += 1
    finally:
        hook = OUT / "hook.log"
        say(f"hook.log exists={hook.exists()} size={hook.stat().st_size if hook.exists() else 0}")
        soft("quit", lambda: j("quit", timeout=90))
        say("done")
        log.close()


if __name__ == "__main__":
    main()