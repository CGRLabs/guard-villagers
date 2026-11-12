"""What moves a provoked guard: the goal names, the path, and the speed.

The chase case of `proof_revenge.py` measured guards covering 0.24-0.32
blocks/tick, barely over a provoked spider's 0.215, so this asked the running
world what it does with the mod's numbers: every four ticks it prints each
guard's running goals, its running target goals, how many path nodes are left,
how far it is from the player and how fast it covered ground between samples.

What it found, at 18 blocks with two sword guards and two archers: the sword
guards ran `MeleeAttack` with a live path and were at the player's feet by the
first sample, while the archers ran `CrossbowAttack` with `path None` and never
came inside 12 blocks in 80 ticks — the goal only paths while the target is
beyond its own range, which was 15. They also shot each other, and the ones
struck took the colleague as their target and forgot the player. Hence
`BOW_RANGE` and the `ignoring` on the revenge goal.
"""

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
HELMET = "minecraft:iron_helmet"
SWORDS = ("minecraft:iron_sword", "minecraft:crossbow")
FLOOR = 89


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--villagers", type=int, default=6)
    ap.add_argument("--off", type=float, default=18.0, help="how far the player steps back")
    ap.add_argument("--samples", type=int, default=20, help="samples, 4 ticks apart")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-chase-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-chase-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "chase-diag.log").open("w", encoding="utf-8")

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
        say(f">> {text}: {json.dumps(value)[:200]}")
        return value

    def wait(ticks):
        for _ in range(4):
            try:
                ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))
                return
            except RuntimeError as exc:
                if "not advancing" not in str(exc):
                    raise
                say(f"paused, taking the game back: {exc}")
                ctl("close")
                ctl("resume")
                time.sleep(1)

    def near(radius=120):
        return ctl("mobs", str(radius))["near"]

    def is_guard(m):
        return m.get("head") == HELMET or m.get("held") in SWORDS

    def guards(radius=120):
        return [m for m in near(radius) if m.get("kind") == VILLAGER and is_guard(m)]

    def player():
        st = ctl("state")
        p = st.get("player") or {}
        return (p.get("position") or [0.0, 0.0, 0.0]), st.get("ticks") or 0

    def goto(at):
        command(f"tp @a {at[0]} {at[1]} {at[2]}")
        ctl("tp", str(at[0]), str(at[1]), str(at[2]))
        wait(20)

    try:
        say("launching VISIBLE window...")
        ctl("launch", "--game", game, "--world", "GuardChaseV07f", "--creative", "--wait",
            "--render-distance", "8", "--resources", args.resources, "--test-terrain",
            timeout=420)
        ctl("wait-ready", "180", timeout=210)
        ctl("options-set", "pauseOnLostFocus", "false")
        ctl("options-set", "tutorialStep", "none")
        command("time set day")
        command("weather clear")
        command("fill -24 89 -40 60 89 45 minecraft:stone")
        for low in range(90, 97, 6):
            command(f"fill -24 {low} -40 60 {min(low + 5, 96)} 45 minecraft:air")
        goto((0, FLOOR + 1.0, 8))
        command("gamemode survival @a")
        command("attribute @p minecraft:max_health base set 100")
        command("effect give @a minecraft:resistance 3600 4 true")
        command("effect give @a minecraft:regeneration 3600 5 true")

        want = -(-args.villagers * 2 // 3)
        # Eight blocks apart: guards take a villager each, so none of them is
        # pushed onto another's head (crowded they collide and climb, and a
        # stacked mob is neither walkable nor hittable).
        for i in range(args.villagers):
            command(f"summon {VILLAGER} {i * 8} 90 0 "
                    f"{{NoAI:1b,VillagerData:{{type:\"minecraft:plains\","
                    f"profession:\"minecraft:farmer\",level:1}}}}")
        deadline = time.monotonic() + 120
        here = []
        while time.monotonic() < deadline:
            here = guards()
            if len(here) >= want:
                break
            wait(10)
        say(f"{len(here)} guards for {args.villagers} villagers, {want} wanted")

        # Where they stand before any of this: what the world carries, and
        # what they are busy with while nobody has struck them.
        at, tick = player()
        for g in here:
            say(f"  at rest guard {g['id']} at {[round(v, 1) for v in g['pos']]} "
                f"ground {g.get('on_ground')} mount {g.get('mount')} "
                f"rider {g.get('rider')} target {g.get('target')!r} "
                f"goals {g.get('goals')} targets {g.get('targets')} "
                f"path {g.get('path')}")
        say(json.dumps(command("execute as @e[type=minecraft:villager,limit=20] run "
                               "attribute @s minecraft:movement_speed base get"
                               ).get("chat")))

        # Strike one guard, from whichever side of it has the clearest line:
        # `attack` swings at whatever the crosshair picks, so a neighbour in
        # the way reads as "out of reach or hidden".
        hit, struck, spot = None, None, None
        for try_ in range(6):
            live = guards()
            if not live:
                raise RuntimeError("no guards left to strike")

            def clear(cand, others):
                return all(math.hypot(o["pos"][0] - cand["pos"][0],
                                       o["pos"][2] - cand["pos"][2]) >= 1.5
                           for o in others if o["id"] != cand["id"])

            for cand in sorted(live, key=lambda g: -min(
                    (math.dist(g["pos"], o["pos"]) for o in live if o["id"] != g["id"]),
                    default=99.0)):
                if not clear(cand, live):
                    continue
                for off in ((0.0, 2.2), (0.0, -2.2)):
                    x, y, z = cand["pos"]
                    at = (round(x + off[0], 1), FLOOR + 1.0, round(z + off[1], 1))
                    health = cand["health"]
                    goto(at)
                    try:
                        ctl("attack", str(cand["id"]), timeout=40)
                    except RuntimeError as exc:
                        say(f"  guard {cand['id']} from {at}: {exc}")
                        continue
                    wait(10)
                    now = {g["id"]: g for g in guards()}.get(cand["id"])
                    if now and now["health"] < health:
                        hit, struck, spot = now, cand["id"], at
                        break
                    say(f"  guard {cand['id']} from {at}: no damage "
                        f"({health} -> {now and now['health']})")
                if hit:
                    break
            if hit:
                break
            say(f"  strike attempt {try_} failed; the village has moved")
            wait(20)
        assert hit, "never struck a guard"
        x, y, z = hit["pos"]
        say(f"struck guard {struck}: target {hit.get('target')!r} "
            f"health {hit['health']} goals {hit.get('goals')} "
            f"targets {hit.get('targets')} path {hit.get('path')}")

        ids = {g["id"]: g.get("held") for g in guards()}
        say("weapons: " + json.dumps({str(k): v for k, v in ids.items()}))
        away = (round(x, 1), FLOOR + 1.0, round(z + args.off, 1))
        goto(away)
        at, tick = player()
        start = {g["id"]: g for g in guards()}
        say(f"the player stands off {round(math.dist(at, [x, y, z]), 1)} blocks; "
            f"watching {args.samples} samples, 4 ticks apart")
        previous = dict(start)
        previous_tick = tick
        fastest = {}
        for i in range(args.samples):
            wait(4)
            at, tick = player()
            now = {g["id"]: g for g in guards()}
            dt = tick - previous_tick
            for gid, g in sorted(now.items()):
                d = round(math.dist(g["pos"], at), 1)
                was = previous.get(gid)
                v = ""
                if was is not None and dt > 0:
                    rate = round(math.dist(g["pos"], was["pos"]) / dt, 3)
                    v = f"{rate} bt"
                    if was is not start.get(gid) and rate > 0.02:
                        fastest.setdefault(gid, []).append(rate)
                say(f"  s{i:02d} guard {gid} {d} blocks off at "
                    f"{[round(p, 1) for p in g['pos']]} target {g.get('target')!r} "
                    f"goals {g.get('goals')} targets {g.get('targets')} "
                    f"path {g.get('path')} {v}")
            previous, previous_tick = now, tick
            if all(math.dist(g["pos"], at) < 3.0 for g in now.values()):
                say(f"  all guards arrived by sample {i}")
                break
        say("mean blocks/tick while moving, per guard:")
        for gid, vals in sorted(fastest.items()):
            say(f"  guard {gid}: {round(sum(vals) / len(vals), 3)} over "
                f"{len(vals)} moving samples")
    finally:
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
