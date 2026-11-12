"""The guard rule on villages of every size, and every spacing.

The promise is one line: a village gets ceil(2n/3) guards and nothing else
changes. This proves it for a village of one and a village of thirty, for two
clusters standing close enough to be one village and two standing far enough to
stay separate, and it keeps watching each case after it settles so a count that
drifts is caught rather than a count that only looked right once.

Every case is its own flat site, its own crowd, nobody else armed: that is what
makes the number unambiguous.
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
CHESTPLATE = "minecraft:iron_chestplate"
SWORDS = ("minecraft:iron_sword", "minecraft:crossbow")
# The village's reach and the guard rule, as the mod has them.
VILLAGE_RADIUS = 32.0


def guards_for(regular):
    return -(-regular * 2 // 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--settle", type=int, default=60, help="seconds to wait for the guards")
    ap.add_argument("--drift", type=int, default=25, help="seconds to keep watching after")
    ap.add_argument("--watch", type=int, default=120,
                    help="seconds the spacing cases are watched for")
    ap.add_argument("--only", default="", help="just these case names, comma separated")
    ap.add_argument("--sizes", default="", help="just these village sizes, comma separated")
    ap.add_argument("--no-clusters", action="store_true", help="skip the spacing cases")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-sizes-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-sizes-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "sizes-v06.log").open("w", encoding="utf-8")
    report = {"game": game, "scratch_home": str(home), "cases": {}}
    cursor = [40]

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
        say(f"command {text}: {json.dumps(value)[:200]}")
        return value

    def wait(ticks):
        for _ in range(4):
            try:
                ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))
                return
            except RuntimeError as exc:
                if "not advancing" not in str(exc):
                    raise
                # A person at the window can pause the game — the log says
                # "Saving and pausing game..." — and a paused world stops
                # ticking while the client still answers commands. Without
                # this every case after that reads as a stalled village.
                report["pauses"] = report.get("pauses", 0) + 1
                say(f"the world is paused, taking it back: {exc}")
                if not playing():
                    raise RuntimeError(f"the world stayed paused: {exc}")

    def playing():
        """Get the screen back to `playing`, the way the launch sequence does."""
        for _ in range(6):
            try:
                if ctl("state").get("screen") == "playing":
                    return True
                ctl("close")
                ctl("resume")
            except Exception as exc:
                say(f"resume: {exc}")
                return False
            time.sleep(1)
        return False

    def mobs(radius=160):
        return [m for m in ctl("mobs", str(radius))["near"] if m.get("kind") == VILLAGER]

    def adults():
        return [m for m in mobs() if not m.get("baby") and m.get("health", 0) > 0]

    def is_guard(m):
        return m.get("head") == HELMET or m.get("held") in SWORDS

    def guards():
        return [m for m in adults() if is_guard(m)]

    def regular():
        return [m for m in adults() if not is_guard(m)]

    def goto(pos):
        x, y, z = pos
        command(f"tp @a {x} {y} {z}")
        ctl("tp", str(x), str(y), str(z))
        wait(30)

    def shot(name, look=None):
        if look is not None:
            ctl("look-at", str(look[0]), str(look[1]), str(look[2]))
        wait(8)
        path = OUT / f"sizes-v06-{name}.png"
        ctl("screenshot", str(path))
        say(f"screenshot {name}: {path}")
        return path

    def build_site(x, y, z, east=32):
        """Flat ground to stand a crowd on: 32 blocks west, `east` blocks east,
        so a cluster placed off to the side is still on built floor rather than
        on whatever the test world generated."""
        command(f"fill {x - 32} {y - 1} {z - 32} {x + east} {y - 1} {z + 32} "
                f"minecraft:stone")
        command(f"fill {x - 32} {y} {z - 32} {x + east} {y + 5} {z + 32} "
                f"minecraft:air")

    def put(x, y, z, n, dx=0):
        """N villagers standing together, a few blocks apart, all watching."""
        for i in range(n):
            px, pz = x + dx + (i % 5) * 2, z + (i // 5) * 2
            command(f'summon {VILLAGER} {px} {y} {pz} {{NoAI:1b,Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",'
                    f'profession:"minecraft:farmer",level:1}}}}')

    def clear_people():
        command("kill @e[type=minecraft:villager]")
        wait(40)

    def crowd(radius=200):
        return [m for m in mobs(radius) if m.get("kind") == VILLAGER]

    def snapshot(x, clusters):
        """Who stands where, as the game reports it: the villagers of the
        clusters, the guards, and how far each guard is from the people it was
        added for. This is the evidence a drifting count needs — whether the
        mob list lost a guard, or the village itself changed shape."""
        people = adults()
        rest = [m for m in people if not is_guard(m)]
        found = [m for m in people if is_guard(m)]

        def group(pos):
            best, index = None, None
            for i, (dx, _) in enumerate(clusters):
                d = abs(pos[0] - (x + dx + 4)) + abs(pos[2] - 1)
                if best is None or d < best:
                    best, index = d, i
            return index

        centres = {}
        for m in rest:
            centres.setdefault(group(m["pos"]), []).append(m["pos"])
        centres = {i: [sum(p[a] for p in v) / len(v) for a in range(3)]
                   for i, v in sorted(centres.items())} if centres else {}
        keep = []
        for m in found:
            near = min((math.dist(m["pos"], c) for c in centres.values()), default=None)
            keep.append({"id": m["id"], "pos": [round(v, 1) for v in m["pos"]],
                         "group": group(m["pos"]), "to_villagers":
                             None if near is None else round(near, 1),
                         "health": m.get("health"), "held": m.get("held")})
        return {"villagers": len(rest), "guards": len(found),
                "villager_ids": sorted(m["id"] for m in rest),
                "centres": {str(i): [round(v, 1) for v in c] for i, c in centres.items()},
                "apart": round(max((math.dist(a, b) for a in centres.values()
                                    for b in centres.values() if a is not b),
                                   default=0.0), 1),
                "guards_here": keep}

    def check_case(name, clusters, expect_villagers, expect_guards, watch=None,
                   result=None):
        """Stand a crowd on its ground, count what the mod adds, keep counting.

        clusters is a list of (x offset, count); expect_guards is what the rule
        works out to for the village or villages the crowd forms. Each case
        takes its own ground, 80 blocks on from the last, so no earlier case is
        close enough to be counted with it. `result` is the caller's dict,
        filled as the case goes: a failure has to leave its counts and
        snapshots behind, not just its message."""
        x, y, z = cursor[0], 90, 0
        cursor[0] += 80
        result = {} if result is None else result
        result.update({"clusters": [[dx, n] for dx, n in clusters],
                       "villagers": expect_villagers,
                       "want_guards": expect_guards, "site": [x, y, z], "trace": []})
        build_site(x, y, z, east=32 + 8 + max(dx for dx, _ in clusters))
        goto((x, y, z + 8))
        for dx, n in clusters:
            put(x, y, z, n, dx)
        wait(20)

        start = snapshot(x, clusters)
        result["summoned"] = start
        assert start["villagers"] == expect_villagers, \
            f"{name}: {start['villagers']} villagers standing, " \
            f"{expect_villagers} summoned"

        deadline = time.monotonic() + args.settle
        now = []
        while time.monotonic() < deadline:
            now = [m for m in adults() if is_guard(m)]
            if len(now) == expect_guards:
                break
            wait(10)
        result["settled_guards"] = len(now)
        assert len(now) == expect_guards, \
            f"{name}: {len(now)} guards for {expect_villagers} villagers in " \
            f"{[n for _, n in clusters]} cluster(s), the rule wants {expect_guards}"

        # Nothing about the village's own people changed: no weapon in an
        # ordinary hand, and the guard count does not move while we watch.
        seconds = args.drift if watch is None else watch
        drift, armed = 0, []
        lowest, highest = expect_guards, expect_guards
        villagers_low, villagers_high = expect_villagers, expect_villagers
        seen = {m["id"] for m in now}
        gone = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            wait(10)
            here = snapshot(x, clusters)
            drift += 1
            rest = [m for m in crowd() if not is_guard(m)]
            armed += [m["id"] for m in rest if m.get("held") is not None]
            lowest, highest = min(lowest, here["guards"]), max(highest, here["guards"])
            villagers_low, villagers_high = min(villagers_low, here["villagers"]), \
                max(villagers_high, here["villagers"])
            for gid in sorted(seen - {g["id"] for g in here["guards_here"]}):
                gone.append({"poll": drift, "id": gid,
                             "last": [g for g in result["trace"][-1]["guards_here"]
                                      if g["id"] == gid] if result["trace"] else []})
            seen = {g["id"] for g in here["guards_here"]}
            if here["guards"] != expect_guards or here["villagers"] != \
                    expect_villagers or drift <= 2 or gone:
                result["trace"].append(here)
        result["polls"] = drift
        result["last"] = snapshot(x, clusters)
        result["lowest"] = lowest
        result["highest"] = highest
        result["villagers_low"] = villagers_low
        result["villagers_high"] = villagers_high
        result["unarmed_villagers"] = not armed
        result["gone"] = gone
        assert not armed, f"{name}: a villager was armed during the watch: {armed}"
        # The crowd itself has to stay put: a village of 5 and a village of 4
        # want 4+3=7 guards, so a guard count that falls by one is the same
        # story as a villager count that falls by one, and saying which is the
        # difference between finding a bug and chasing one.
        assert villagers_low == villagers_high == expect_villagers, \
            f"{name}: the crowd changed while we watched: {villagers_low} to " \
            f"{villagers_high} of {expect_villagers} villagers, guards " \
            f"{lowest} to {highest} — {[t['villagers'] for t in result['trace'][-6:]]}"
        assert lowest == expect_guards and highest == expect_guards, \
            f"{name}: the guard count drifted between {lowest} and {highest}, " \
            f"the rule wants {expect_guards}"

        # The guards are the only ones wearing the armour.
        text = json.dumps(command("execute as @e[type=minecraft:villager] run "
                                  "data get entity @s equipment"))
        armoured = text.count(CHESTPLATE)
        result["armoured"] = armoured
        assert armoured == expect_guards, \
            f"{name}: {armoured} wear the chestplate, {expect_guards} are guards"
        for m in [g for g in adults() if is_guard(g)]:
            assert m.get("held") in SWORDS, f"{name}: a guard holds nothing: {m}"
        result["passed"] = True
        say(f"{name}: {expect_villagers} villagers -> {expect_guards} guards "
            f"(rule wants {expect_guards}), steady over {drift} polls")
        return result

    def start():
        say("launching VISIBLE window...")
        ctl("launch", "--game", game, "--world", "GuardSizesV06", "--creative", "--wait",
            "--render-distance", "8", "--resources", args.resources, "--test-terrain",
            timeout=420)
        ctl("wait-ready", "120", timeout=150)
        ctl("options-set", "pauseOnLostFocus", "false")
        assert playing(), "game did not enter playing state"
        ctl("options-set", "tutorialStep", "none")
        ctl("key", "f1", "tap")
        command("time set day")
        command("weather clear")
        command("difficulty peaceful")
        ctl("tp", "0", "90", "0")
        wait(10)

    def ensure():
        """A session that went away (window closed, client crashed) comes back
        before the next case rather than failing every case after it."""
        try:
            ctl("state", timeout=30)
            return
        except Exception as exc:
            say(f"the session is gone ({exc}); launching another")
        report["relaunches"] = report.get("relaunches", 0) + 1
        start()

    try:
        say(f"scratch home: {home}")
        start()

        # The sizes worth arguing about: the remainders, where the rounding
        # shows, and the big villages a world actually generates.
        sizes = [int(v) for v in args.sizes.split(",") if v] or \
                [1, 2, 3, 4, 5, 6, 8, 9, 13, 20, 30]
        specs = [(f"village-{n}", [(0, n)], n, guards_for(n), args.drift) for n in sizes]
        # Two clusters of five: close enough to be one village, the rule over
        # all ten; far enough to stay two, the rule for each. The totals differ
        # (7 against 8), so this measures the reach rather than the rounding,
        # and it is watched longer — a count that only looks right for a
        # moment is exactly the failure the spacing cases are here to catch.
        if not args.no_clusters:
            specs.append(("clusters-20-apart", [(0, 5), (20, 5)], 10,
                          guards_for(10), args.watch))
            specs.append(("clusters-60-apart", [(0, 5), (60, 5)], 10,
                          guards_for(5) + guards_for(5), args.watch))

        wanted = {v.strip() for v in args.only.split(",") if v.strip()}
        failures = []
        for name, clusters, people, want, watch in specs:
            if wanted and name not in wanted:
                continue
            # The case's own dict is registered before it runs, so the counts
            # and snapshots it got through stay in the report when it fails.
            cases = report["cases"][name] = {"clusters": [[d, n] for d, n in clusters]}
            try:
                ensure()
                clear_people()
                cases.update(check_case(name, clusters, people, want, watch,
                                        result=cases))
                if name in ("village-1", "village-13", "village-30"):
                    x = cases["site"][0]
                    cases["shot"] = str(shot(name, (x + 3, 91.5, 3)))
            except Exception as exc:
                cases["error"] = str(exc)
                failures.append(f"{name}: {exc}")
                say(f"{name} FAILED: {exc}")
                for seen in (cases.get("trace") or [])[-3:]:
                    say(f"  {name}: {seen['guards']} guards, "
                        f"{seen['villagers']} villagers, clusters "
                        f"{seen['apart']} apart, {seen['guards_here']}")

        clear_people()
        report["failures"] = failures
        report["passed"] = not failures
        say(json.dumps({k: v.get("settled_guards", "failed")
                        for k, v in report["cases"].items()}))
        assert not failures, "; ".join(failures)
    except Exception as exc:
        report["error"] = str(exc)
        say(f"FAILED: {exc}")
        raise
    finally:
        (OUT / "sizes-v06-report.json").write_text(json.dumps(report, indent=2),
                                                   encoding="utf-8")
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
