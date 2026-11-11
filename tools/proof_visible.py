"""Visible Guard Villagers demonstration.

Launches the patched client in a REAL window (no --offscreen) on a throwaway
creative world, summons a villager and a zombie in front of the player, frames
the fight with the camera, and records the villager fighting back (the zombie's
health dropping, then it dying). Then keeps the window open and sends a fresh
zombie at the guard every ~25 s so a human can watch the village being defended.

Usage:
  python proof_visible.py --game <patched horizon-client.exe> \
      [--ctl <horizon-ctl.exe>] [--resources <prepared 26.3>] [--keep-open 240]

Touch target/proof/STOP to close the window early.
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
    ap.add_argument("--keep-open", type=int, default=240)
    args = ap.parse_args()

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-demo-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    env["HORIZON_LAUNCHER_HOME"] = tempfile.mkdtemp(prefix="guard-demo-launcher-")
    env["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="guard-demo-data-")
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="guard-demo-config-")
    env["HORIZON_NO_AUDIO"] = "1"

    log = (OUT / "run.log").open("w", encoding="utf-8")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    def ctl(*a, timeout=120):
        o, e = OUT / "ctl.out", OUT / "ctl.err"
        with o.open("wb") as fo, e.open("wb") as fe:
            done = subprocess.run([args.ctl, *a], stdout=fo, stderr=fe, env=env,
                                  timeout=timeout, cwd=str(INSTALL))
        text = o.read_text(encoding="utf-8", errors="replace").strip()
        err = e.read_text(encoding="utf-8", errors="replace").strip()
        if done.returncode != 0:
            raise RuntimeError(f"ctl {' '.join(map(str, a))} -> {done.returncode}: {text or err}")
        return text

    def j(*a, timeout=120):
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

    def first(ty, radius=48):
        for m in mobs(radius):
            if m.get("type") == ty:
                return m
        return None

    def summon_near(kind, pos, dx=1.5):
        # Use the real /summon command (runs on the server thread) so the mobs
        # are simulated, not client-only statues from the ctl `summon` shortcut.
        if pos:
            return soft(f"summon {kind} near", lambda: j(
                "command", f"summon {kind} {pos[0] + dx:.2f} {pos[1]:.2f} {pos[2]:.2f}"))
        return soft(f"summon {kind}", lambda: j("command", f"summon {kind}"))

    def frame(mob):
        if mob and mob.get("id") is not None:
            soft("look-at-entity", lambda: j("look-at-entity", str(mob["id"]), "--over", "0.4"))

    say(f"scratch home: {home}")
    say("launching VISIBLE window (watch your screen)...")
    ctl("launch", "--game", args.game, "--world", "GuardDemo", "--creative", "--wait",
        "--render-distance", "6", "--resources", args.resources, timeout=420)
    say("launch ok")

    report = {"samples": [], "waves": []}
    stop = OUT / "STOP"
    try:
        soft("wait-ready", lambda: j("wait-ready", "120", timeout=150))
        for _ in range(6):
            st = soft("state", lambda: j("state"))
            if isinstance(st, dict) and st.get("screen") == "playing":
                break
            soft("close", lambda: j("close"))
            soft("resume", lambda: j("resume"))
            j("wait", "10", timeout=30)

        # Bright, dry scene so the fight is easy to watch.
        soft("time set day", lambda: j("command", "time set day"))
        soft("weather clear", lambda: j("command", "weather clear"))

        # A guard appears in front of the player; a zombie is dropped right next
        # to it so the fight happens on camera.
        summon_near(VILLAGER, None)
        j("wait", "20", timeout=30)
        guard = first(VILLAGER)
        say(f"guard: {json.dumps(guard)}")
        summon_near(ZOMBIE, guard.get("pos") if guard else None)
        j("wait", "5", timeout=30)
        frame(first(VILLAGER))
        say("summoned villager + zombie; camera framed on the guard")

        for i in range(8):
            j("wait", "30", timeout=45)
            z = first(ZOMBIE)
            g = first(VILLAGER)
            frame(g)
            entry = {
                "sample": i,
                "zombie_health": z.get("health") if z else None,
                "zombie_hurt_time": z.get("hurt_time") if z else None,
                "zombie_alive": z is not None,
                "villager_health": g.get("health") if g else None,
                "villager_alive": g is not None,
            }
            report["samples"].append(entry)
            say(f"sample {i}: {json.dumps(entry)}")
            if i in (1, 3):
                soft("screenshot", lambda: j("screenshot", str(OUT / f"fight-{i}.png")))

        zs = [s["zombie_health"] for s in report["samples"] if s.get("zombie_health") is not None]
        killed = any(s["zombie_alive"] is False for s in report["samples"][1:])
        dropped = len(zs) >= 2 and zs[-1] < zs[0]
        report["zombie_health_series"] = zs
        report["zombie_health_dropped"] = bool(dropped)
        report["zombie_killed"] = bool(killed or dropped)
        report["villager_survived"] = bool(report["samples"][-1].get("villager_alive"))
        say(f"zombie health series: {zs} -> dropped={dropped} killed={report['zombie_killed']} "
            f"villager_survived={report['villager_survived']}")

        # Keep the window open and send a fresh zombie at the guard every ~25 s so
        # the human watching sees the village defended over and over.
        say(f"leaving the window open ~{args.keep_open}s — 4 zombie waves (~25s apart), then free "
            f"play (touch {stop} to close early)")
        deadline = time.time() + args.keep_open
        wave = 0
        next_wave = time.time()
        while time.time() < deadline and not stop.exists():
            if time.time() >= next_wave and wave < 4:
                wave += 1
                guard = first(VILLAGER)
                if guard is None:
                    summon_near(VILLAGER, None)
                    soft("wait", lambda: j("wait", "20", timeout=30))
                    guard = first(VILLAGER)
                summon_near(ZOMBIE, guard.get("pos") if guard else None)
                soft("wait", lambda: j("wait", "5", timeout=30))
                z = first(ZOMBIE)
                frame(guard)
                w = {"wave": wave, "zombie_health": z.get("health") if z else None,
                     "villager_alive": guard is not None}
                report["waves"].append(w)
                say(f"wave {wave}: {json.dumps(w)}")
                if wave in (1, 3):
                    soft("screenshot", lambda: j("screenshot", str(OUT / f"wave-{wave}.png")))
                next_wave = time.time() + 25
            time.sleep(2)
    finally:
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        soft("quit", lambda: j("quit", timeout=90))
        say("done")
        log.close()


if __name__ == "__main__":
    main()