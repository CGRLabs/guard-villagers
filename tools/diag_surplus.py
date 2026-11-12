"""Who exactly is armed, every twenty ticks, in a village of ten.

`proof_revenge.py` measured the same village twice and got two different
answers: seven guards on the run's first pass, eight on the third
(`{0.5: 10, 0.62: 8}` from the world's own attribute read). The rule says
`ceil(10 x 2/3) = 7`, so the eighth is either a mob the village counted twice,
a corpse still in the entity list, or somebody else's villager that the
attribute command reaches and the mob list does not.

This stands in the proof's exact village — the same arena, the same ten
summoned villagers, the same strike on the walking one — and prints the whole
roster instead of a number: every villager's id, its distance from the village,
whether it carries the guard's armour, its health and whether it is a baby. Any
eighth armed mob has to show up in that list with one of those four fields
pointing at it.

The suspicion the roster has to settle: a villager here has its AI on and walks,
and a group of villagers that stands more than a village's width (32 blocks)
from every other one is its own village — one person, and `ceil(1 x 2/3) = 1`
guard. An eighth armed mob out there with a stray farmer beside it is the rule
working on a splinter, not a second guard for the same village. Summoning one
lone villager in this arena does get a guard within seconds, which is what
pointed here.
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
A = (0.0, 90.0, 0.0)
WALKER_AT = [12, 90, 10]


def guards_for(regular):
    return -(-regular * 2 // 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources",
                    default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--samples", type=int, default=40)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-surplus-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-surplus-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "surplus-diag.log").open("w", encoding="utf-8")

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

    def command(text, quiet=False):
        value = ctl("command", text)
        if not quiet:
            say(f">> {text}: {json.dumps(value)[:160]}")
        return value

    def soft(text):
        try:
            command(text, quiet=True)
        except Exception as exc:
            say(f"  {text}: {exc}")

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

    def goto(at):
        x, y, z = at
        command(f"tp @a {x} {y} {z}", quiet=True)
        ctl("tp", str(x), str(y), str(z))
        wait(15)

    def people():
        """Every villager in the loaded world, alive or not, baby or not."""
        out = []
        for m in ctl("mobs", "400")["near"]:
            if m.get("kind") != VILLAGER:
                continue
            out.append({
                "id": m["id"],
                "pos": [round(v, 1) for v in m["pos"]],
                "dist": round(math.dist(m["pos"], A), 1),
                "armed": m.get("head") == HELMET or m.get("held") in SWORDS,
                "held": m.get("held"),
                "health": m.get("health"),
                "baby": bool(m.get("baby")),
                "target": m.get("target"),
            })
        return out

    def speed_counts():
        """The world's own answer for how many villagers stand on each speed."""
        value = command("execute as @e[type=minecraft:villager,limit=60] run "
                        "attribute @s minecraft:movement_speed base get", quiet=True)
        found = {}
        for line in value.get("chat", []):
            for number in re_numbers(line):
                speed = float(number)
                if 0.0 < speed <= 2.0:
                    found[speed] = found.get(speed, 0) + 1
        return found

    def re_numbers(line):
        import re
        return re.findall(r"\d+\.\d+", line)

    def roster(people_):
        for p in sorted(people_, key=lambda p: (not p["armed"], p["id"])):
            say(f"    {p['id']:>5} armed={int(p['armed'])} baby={int(p['baby'])} "
                f"hp={p['health']} at {p['pos']} {p['dist']} off "
                f"held={p['held']} target={p['target']}")

    say("launching VISIBLE window...")
    ctl("launch", "--game", game, "--world", "GuardSurplusV07", "--creative",
        "--wait", "--render-distance", "8", "--resources", args.resources,
        "--test-terrain", timeout=420)
    ctl("wait-ready", "180", timeout=210)
    ctl("options-set", "pauseOnLostFocus", "false")
    ctl("options-set", "tutorialStep", "none")
    ctl("key", "f1", "tap")
    command("time set day")
    command("weather clear")
    command(f"fill -24 {FLOOR} -24 80 {FLOOR} 24 minecraft:stone")
    for low in range(FLOOR + 1, FLOOR + 8, 6):
        command(f"fill -24 {low} -24 80 {min(low + 5, FLOOR + 7)} 24 minecraft:air",
                quiet=True)
    goto((0, FLOOR + 1.0, 8))

    command("kill @e[type=minecraft:villager]", quiet=True)
    wait(40)
    command("gamemode survival @a")
    soft("difficulty easy")
    soft("attribute @p minecraft:max_health base set 100")
    soft("effect give @a minecraft:resistance 3600 4 true")

    def put(at, n, walker=False):
        x, y, z = at
        for i in range(n):
            px, pz = x + (i % 5) * 2, z + (i // 5) * 2
            head = "{" if walker else "{NoAI:1b,"
            command(f'summon {VILLAGER} {px} {y} {pz} {head}Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",'
                    f'profession:"minecraft:farmer",level:1}}}}', quiet=True)

    put(A, 9)
    wait(5)
    put(WALKER_AT, 1, walker=True)
    say("ten villagers stand here: nine still, one at 12,10 with its AI on")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if sum(1 for p in people() if p["armed"]) >= guards_for(10):
            break
        wait(10)
    here = min((p for p in people() if not p["armed"]),
               key=lambda p: math.dist(p["pos"], WALKER_AT))
    walker = here["id"]
    say(f"{walker} is the one that walks")

    # The proof's control case, step for step: stand by the walking villager and
    # strike it, then watch. The surplus appeared after this in run 9.
    here = [p for p in people() if p["id"] == walker][0]
    x, _, z = here["pos"]
    goto((round(x + 1.6, 1), FLOOR + 1.0, round(z, 1)))
    try:
        ctl("attack", str(walker), timeout=40)
    except RuntimeError as exc:
        say(f"attack: {exc}")
    wait(10)

    armed_before = None
    for sample in range(args.samples):
        wait(20)
        ps = people()
        armed = [p for p in ps if p["armed"]]
        speeds = speed_counts()
        line = (f"t+{sample * 20:>4} villagers={len(ps):>2} armed={len(armed):>2} "
                f"babies={sum(1 for p in ps if p['baby'])} "
                f"dead={[p['id'] for p in ps if (p['health'] or 0) <= 0]} "
                f"far={[p['id'] for p in ps if p['dist'] > 32]} "
                f"speeds={speeds}")
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()
        if len(armed) != guards_for(10):
            say("  ROSTER (the count is off the rule):")
            roster(ps)
        if armed_before is None:
            armed_before = len(armed)
    say(f"seven is what ceil(10 x 2/3) asks for; the last sample said "
        f"{len([p for p in people() if p['armed']])}")
    roster(people())
    try:
        ctl("quit", timeout=90)
    except Exception as exc:
        say(f"quit: {exc}")
    log.close()


if __name__ == "__main__":
    main()
