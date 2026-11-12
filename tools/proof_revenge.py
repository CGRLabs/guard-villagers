"""The village answers a struck guard, and only a struck guard.

Four claims, each measured in a running world:

* strike a guard and every guard of its village takes the player as their
  target, and comes;
* strike an ordinary villager and nobody is called — the guards stay
  targetless;
* a guard of the next village may stand in sight of its neighbours beating the
  player and stay out of it until something strikes it;
* the chase outruns what the guards are called out to run at, measured against
  a monster coming for the player in the same world on the same ground.

Two of the mod's numbers shape the tests. A guard's call reaches
`follow_range` (32 blocks) around the one that was struck, and the same number
is how far it will hold a grudge: run past 32 and it loses you. So every
distance below is inside one village's width, and the bystander village stands
45 off — out of the call, in sight of the blow.

The player has to be in survival: a creative player is immune, and an immune
player is no one's target. So the run is built to survive being beaten —
resistance, regeneration, and a health bar that can absorb a village.

The villager the control strikes is the one here with its AI on, so it can
think and move: at this Horizon revision a villager has no goals at all
(`mobs/villager.rs:46`, "its brain does everything, it has no goals"), so a
thinking one is the stronger case to rule out, not a weaker one. What the
control measures is that the call lives in the guard's own revenge goal and in
nothing else.

That villager is also why the yardstick is a monster and not a mob ambling
about: on generated flat ground an unbothered villager does not walk anywhere
— the first run of this proof watched one for 300 ticks and measured 0.001
blocks/tick — so there is no idle villager speed to compare a chase with.
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
MONSTER = "minecraft:spider"
HELMET = "minecraft:iron_helmet"
SWORDS = ("minecraft:iron_sword", "minecraft:crossbow")
# The mod's own numbers, as the proof has to read them.
VILLAGE_RADIUS = 32.0
GUARD_SPEED = 0.62         # runtime.rs: what a guard's legs are set to
CHASE_SPEED = 1.5          # runtime.rs: what the attack goals multiply them by
BOW_RANGE = 6.0            # runtime.rs: how close an archer comes to loose
FARMER_SPEED = 0.5         # game/mods.rs: what a villager's legs are
FLOOR = 89              # standing on the arena floor puts you at y = 90
A = (0.0, 90.0, 0.0)    # the first village
B = (45.0, 90.0, 0.0)   # the next: 45 off, past the call, inside sight
WALKER_AT = [12, 90, 10]    # where the one villager with its AI stands
SPIDER_AT = 62.0          # where the yardstick monster is summoned, on the arena's far side


def guards_for(regular):
    return -(-regular * 2 // 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--ctl", default=str(INSTALL / "horizon-ctl.exe"))
    ap.add_argument("--resources", default=str(INSTALL / ".local" / "horizon-client" / "26.3"))
    ap.add_argument("--settle", type=int, default=90, help="seconds for a village to arm")
    ap.add_argument("--chase", type=int, default=80, help="ticks the guards are followed")
    ap.add_argument("--reach", type=int, default=120, help="seconds for a guard to arrive")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    game = str(Path(args.game).resolve())

    env = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="guard-revenge-home-"))
    env["HORIZON_HOME"] = str(home)
    env["HORIZON_CONTROL"] = str(home / "control.sock")
    for key in ("HORIZON_LAUNCHER_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env[key] = tempfile.mkdtemp(prefix="guard-revenge-")
    env["HORIZON_NO_AUDIO"] = "1"
    env["HORIZON_LAUNCHER_NO_SELF_UPDATE"] = "1"
    log = (OUT / "revenge-v07.log").open("w", encoding="utf-8")
    report = {"game": game, "scratch_home": str(home), "cases": {}, "relaunches": 0}

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
        try:
            value = ctl("command", text)
        except RuntimeError as exc:
            say(f"command {text} FAILED: {exc}")
            raise
        say(f"command {text}: {json.dumps(value)[:160]}")
        return value

    def soft(text):
        """A command the run only needs as a comfort, not as a proof."""
        try:
            command(text)
        except Exception as exc:
            say(f"  (not applied: {exc})")

    def wait(ticks):
        for _ in range(4):
            try:
                ctl("wait", str(ticks), timeout=max(30, ticks // 20 + 20))
                return
            except RuntimeError as exc:
                if "not advancing" not in str(exc):
                    raise
                report["pauses"] = report.get("pauses", 0) + 1
                say(f"the world is paused, taking it back: {exc}")
                if not playing():
                    raise RuntimeError(f"the world stayed paused: {exc}")

    def playing():
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

    def mobs(radius=200):
        return [m for m in ctl("mobs", str(radius))["near"] if m.get("kind") == VILLAGER]

    def is_guard(m):
        return m.get("head") == HELMET or m.get("held") in SWORDS

    def brief(m, at):
        return {"id": m["id"], "pos": [round(v, 1) for v in m["pos"]],
                "target": m.get("target"), "health": m.get("health"),
                "dist": round(math.dist(m["pos"], at), 1)}

    def frame():
        """Where the player, the guards and the villagers are, this tick."""
        st = ctl("state")
        p = st.get("player") or {}
        at = p.get("position") or [0.0, 0.0, 0.0]
        here = [m for m in mobs() if not m.get("baby") and m.get("health", 0) > 0]
        return {"tick": st.get("ticks"), "player": [round(v, 1) for v in at],
                "health": p.get("health"),
                "guards": [brief(m, at) for m in here if is_guard(m)],
                "farmers": [brief(m, at) for m in here if not is_guard(m)]}

    def find(fr, mid):
        for key in ("guards", "farmers"):
            for m in fr[key]:
                if m["id"] == mid:
                    return m
        return None

    def on_player(frames, ids):
        """Which of `ids` ever held the player as their target."""
        return sorted({m["id"] for f in frames for m in f["guards"]
                       if m["id"] in ids and m["target"] == "Player"})

    def goto(at):
        x, y, z = at
        command(f"tp @a {x} {y} {z}")
        ctl("tp", str(x), str(y), str(z))
        wait(20)

    def protect():
        """Survival, and the means to stay in it while a village hits us."""
        command("gamemode survival @a")
        soft("difficulty easy")
        soft("attribute @p minecraft:max_health base set 100")
        soft("effect give @a minecraft:resistance 3600 4 true")
        soft("effect give @a minecraft:regeneration 3600 5 true")
        wait(10)
        fr = frame()
        report["health_after_protect"] = fr["health"]
        say(f"the test player stands in survival at {fr['health']} health")

    def heal():
        soft("effect give @a minecraft:regeneration 600 5 true")
        soft("effect give @a minecraft:resistance 3600 4 true")

    def open_side(fr, mid, skip=0):
        """Somewhere to stand for a swing at `mid`: about two blocks off it, in
        a direction with no other body near it.

        `attack` turns to the named entity and then hits whatever the crosshair
        actually picks, so a neighbour standing between the player and the guard
        eats the blow and the guard never learns anything. Measured in the world:
        with two villages in one arena, swinging from whichever side the target
        stood on failed three times running with `that entity is out of reach or
        hidden`; choosing a side the crowd leaves open is what got through.
        """
        here = find(fr, mid)
        if here is None:
            raise RuntimeError(f"entity {mid} is gone")
        others = [m for key in ("guards", "farmers") for m in fr[key]
                  if m["id"] != mid]
        spots = []
        for dx, dz in ((1.6, 0.0), (-1.6, 0.0), (0.0, 1.6), (0.0, -1.6),
                       (1.3, 1.3), (-1.3, 1.3), (1.3, -1.3), (-1.3, -1.3)):
            x, z = here["pos"][0] + dx, here["pos"][2] + dz
            room = min([math.dist((x, z), (o["pos"][0], o["pos"][2]))
                        for o in others] or [99.0])
            spots.append(((x, z), room))
        # Stand where nothing else stands. A village packed in a two-block grid
        # can leave no such place, and then the roomiest of the lot still beats
        # giving up — that is where the blow used to land on a neighbour.
        free = [s for s, room in spots if room >= 2.0]
        chosen = free or [s for s, _ in sorted(spots, key=lambda t: -t[1])]
        return chosen[skip % len(chosen)] if chosen else None

    def stand_next_to(mid, tries=8):
        """Get within a survival reach of one entity, on ground clear of the
        neighbours, and stay there."""
        last = None
        for attempt in range(tries):
            fr = frame()
            here = find(fr, mid)
            if here is None:
                raise RuntimeError(f"entity {mid} is gone")
            spot = open_side(fr, mid, skip=attempt)
            if spot is None:
                last = f"{mid} has no clear ground beside it ({here['dist']} blocks off)"
                wait(10)
                continue
            x, z = spot
            goto((round(x, 1), FLOOR + 1.0, round(z, 1)))
            fr = frame()
            now = find(fr, mid)
            if now and now["dist"] < 3.2:
                return fr
            last = f"{mid} stands {now and now['dist']} blocks off"
            wait(10)
        raise RuntimeError(f"could not get at {mid}: {last}")

    def reachable(ids):
        """The nearest of `ids` a swing can be aimed at without going through
        somebody else: two villages in one arena is a crowd, and a struck
        bystander would prove nothing about who answers."""
        fr = frame()
        near = sorted((g for g in fr["guards"] if g["id"] in ids),
                      key=lambda g: g["dist"])
        assert near, f"none of {sorted(ids)} is in sight"
        for cand in near:
            if open_side(fr, cand["id"]) is not None:
                return cand
        return near[0]

    def hit(mid):
        """Strike one entity, and prove the blow landed by its health."""
        before = stand_next_to(mid)
        m = find(before, mid)
        for _ in range(3):
            try:
                ctl("attack", str(mid), timeout=40)
            except RuntimeError as exc:
                say(f"  attack {mid}: {exc}")
                wait(10)
                before = stand_next_to(mid)
                m = find(before, mid)
                continue
            wait(8)
            after = frame()
            now = find(after, mid)
            after["struck"] = {"id": mid, "before": m["health"],
                               "after": now and now["health"]}
            if after["health"] is not None:
                report["health_min"] = min(after["health"],
                                           report.get("health_min", after["health"]))
            if now and now["health"] < m["health"]:
                say(f"struck {mid}: health {m['health']} -> {now['health']}")
                return after
            say(f"  attack {mid} landed no damage ({m['health']} -> "
                f"{now and now['health']}); trying again")
        raise RuntimeError(f"{mid} took no damage: the player never reached it")

    def watch(ticks, step=4):
        out = []
        for _ in range(max(1, ticks // step)):
            wait(step)
            fr = frame()
            if fr["health"] is not None and fr["health"] <= 2:
                raise RuntimeError(f"the test player is dying ({fr['health']} "
                                   f"health): the protections failed")
            out.append(fr)
        return out

    def speeds(frames, key="guards"):
        """Blocks per tick each entity of `key` covered."""
        per = {}
        for a, b in zip(frames, frames[1:]):
            dt = (b["tick"] or 0) - (a["tick"] or 0)
            if dt <= 0:
                continue
            for m in b[key]:
                was = find(a, m["id"])
                if was is None:
                    continue
                per.setdefault(m["id"], []).append(math.dist(m["pos"], was["pos"]) / dt)
        return {i: round(sum(v) / len(v), 3) for i, v in sorted(per.items())}

    def going(frames, mid, key="farmers"):
        """How fast one entity goes when it is actually going: the mean over
        the samples in which it moved at all. Standing still is not a speed,
        and a mob spends most of its day doing it."""
        vals = []
        for a, b in zip(frames, frames[1:]):
            dt = (b["tick"] or 0) - (a["tick"] or 0)
            m, n = find(a, mid), find(b, mid)
            if dt > 0 and m and n:
                v = math.dist(m["pos"], n["pos"]) / dt
                if v > 0.02:
                    vals.append(v)
        return (round(sum(vals) / len(vals), 3) if vals else 0.0, len(vals))

    def closing(frames, ids=None, key="guards"):
        """How much nearer each entity got to the player, and how fast it
        covered ground — the chase is how far it came, not how far it
        strolled: a villager that wanders off covers ground too."""
        dt = (frames[-1]["tick"] or 0) - (frames[0]["tick"] or 0)
        out = []
        for last in frames[-1][key]:
            if ids is not None and last["id"] not in ids:
                continue
            series = [m for m in (find(f, last["id"]) for f in frames) if m]
            if len(series) < 2 or not dt:
                continue
            moved = sum(math.dist(a["pos"], b["pos"])
                        for a, b in zip(series, series[1:]))
            out.append({"id": last["id"], "from": series[0]["dist"],
                        "to": last["dist"],
                        "nearest": round(min(m["dist"] for m in series), 1),
                        "covered": round(moved / dt, 3)})
        return out

    def closing_pace(frames, ids, key="guards", beyond=5.0):
        """Blocks per tick each of `ids` took off its distance to the player
        while it still had ground to make up. This is the chase: a guard
        milling at your feet is not running, and a guard standing 14 blocks
        off and shooting is not running either, so the pace is read only from
        the samples in which it came closer from more than `beyond` blocks."""
        out = {}
        for a, b in zip(frames, frames[1:]):
            dt = (b["tick"] or 0) - (a["tick"] or 0)
            if dt <= 0:
                continue
            for now in b[key]:
                if ids is not None and now["id"] not in ids:
                    continue
                was = find(a, now["id"])
                if was is None or was["dist"] <= beyond:
                    continue
                if now["dist"] >= was["dist"]:
                    continue
                out.setdefault(now["id"], []).append(
                    (was["dist"] - now["dist"]) / dt)
        return {i: round(sum(v) / len(v), 3) for i, v in sorted(out.items()) if v}

    def build_arena():
        command(f"fill -24 {FLOOR} -24 80 {FLOOR} 24 minecraft:stone")
        # One layer of this arena is 5145 blocks and a fill takes 32768, so the
        # air above goes in six layers at a time.
        for low in range(FLOOR + 1, FLOOR + 8, 6):
            command(f"fill -24 {low} -24 80 {min(low + 5, FLOOR + 7)} 24 minecraft:air")

    def attribute_speeds():
        """The movement speed the running world gives each of the village's
        people, read with the `attribute` command instead of from the mod's
        source. This is the structural half of the chase claim: a guard stands
        on a farmer's ground with a farmer's body, so the only difference in
        how fast the two can go is the number the world carries."""
        value = command("execute as @e[type=minecraft:villager,limit=60] run "
                        "attribute @s minecraft:movement_speed base get")
        found = {}
        for line in value.get("chat", []):
            for number in re.findall(r"\d+\.\d+", line):
                speed = float(number)
                if 0.0 < speed <= 2.0:
                    found[speed] = found.get(speed, 0) + 1
        return found

    def monster_baseline(ticks=240):
        """How fast a monster comes for the player — the yardstick for "run
        fast", measured in this same world on the same ground the guards run
        over.

        A villager is no yardstick: left alone on generated ground one stands
        where it was put, 0.001 blocks/tick over 300 ticks of calm, so there is
        no villager speed to measure until it has a reason to move. What moves
        one is a monster, and a monster coming for the player is the honest
        comparison anyway: it is the thing a guard is called out to run at.

        It is a spider rather than a zombie because it is the middle of the day
        and a zombie spends it running from the sun rather than at us. A spider
        in sunlight takes no notice of anybody either — it is neutral until it
        is struck — so the proof strikes it, the same way it strikes a guard,
        and then steps back off it. The measurement is of a provoked monster,
        which is exactly the provocation the chase claim is about.

        The run-up is repeated from farther off until there are three samples of
        it to average: measured once, the provoked spider was on the player
        inside a single 6-tick sample, and one sample is an arrival, not a pace.
        15 blocks is the longest run-up tried because that is a spider's own
        follow range — beyond it the grudge lapses and nothing comes.
        """
        for back in (8.0, 13.0, 15.0):
            command(f"kill @e[type={MONSTER}]")
            wait(10)
            # Close enough for the mob list to see it: `mobs 60` is a radius
            # around the player, and the player is at the village 62 blocks from
            # this post until the run-up takes them away.
            goto((round(SPIDER_AT + 6, 1), FLOOR + 1.0, 0.0))
            stand = (round(SPIDER_AT + back, 1), FLOOR + 1.0, 0.0)
            POST = [SPIDER_AT, FLOOR + 1.0, 0.0]
            before = {m["id"] for m in ctl("mobs", "60")["near"]}
            command(f"summon minecraft:spider {SPIDER_AT} {FLOOR + 1} 0")
            wait(10)
            fresh = [m for m in ctl("mobs", "60")["near"]
                     if m["id"] not in before and m.get("kind") == MONSTER]
            assert fresh, "no spider appeared where it was summoned"
            mine = min(fresh, key=lambda m: math.dist(m["pos"], POST))
            mid = mine["id"]

            # Strike it, then stand off again and let it come.
            x, y, z = mine["pos"]
            goto((round(x + 1.6, 1), FLOOR + 1.0, round(z, 1)))
            ctl("attack", str(mid), timeout=40)
            wait(10)
            here = [m for m in ctl("mobs", "60")["near"] if m["id"] == mid]
            assert here, f"the spider {mid} vanished before it could be provoked"
            took = here[0].get("target")
            assert took == "Player", \
                f"striking the spider left it with no grudge: target {took!r}"
            say(f"struck the spider {mid}: it takes the player as its target, "
                f"and {back} blocks are the run-up")
            goto(stand)

            frames = []
            for _ in range(ticks // 4):
                wait(4)
                st = ctl("state")
                p = (st.get("player") or {}).get("position") or [0.0, 0.0, 0.0]
                now = [m for m in ctl("mobs", "60")["near"] if m["id"] == mid]
                if not now:
                    break
                frames.append({"tick": st.get("ticks") or 0,
                               "pos": now[0]["pos"],
                               "target": now[0].get("target"),
                               "dist": round(math.dist(now[0]["pos"], p), 1)})
                if frames[-1]["dist"] <= 1.5:
                    break
            command(f"kill @e[type={MONSTER}]")
            wait(20)
            vals = [math.dist(a["pos"], b["pos"]) / (b["tick"] - a["tick"])
                    for a, b in zip(frames, frames[1:]) if b["tick"] > a["tick"]]
            running = [v for v in vals if v > 0.02]
            if len(running) < 3:
                say(f"the provoked spider covered the {back} blocks inside "
                    f"{len(frames)} samples; taking a longer run-up")
                continue
            came = min(f["dist"] for f in frames)
            speed = round(sum(running) / len(running), 3)
            assert came <= 3.0, \
                f"the spider {mid} never reached the player: {came} blocks"
            say(f"a provoked spider comes at the player at {speed} blocks/tick "
                f"({len(running)} of {len(frames)} samples), and got to {came}")
            return speed, len(running), came, mid, frames[:2] + frames[-2:]
        raise RuntimeError("no monster pace to compare the guards with: every "
                           "run-up ended before three samples of it could be "
                           "measured")

    def put(at, n, walker=None):
        """n villagers standing together; `walker`, one of them by index, keeps
        its AI, so the run has a villager's own walking speed to compare a
        guard's chase with."""
        x, y, z = at
        for i in range(n):
            px, pz = x + (i % 5) * 2, z + (i // 5) * 2
            head = "{" if i == walker else "{NoAI:1b,"
            command(f'summon {VILLAGER} {px} {y} {pz} {head}Rotation:[180f,0f],'
                    f'VillagerData:{{type:"minecraft:plains",'
                    f'profession:"minecraft:farmer",level:1}}}}')

    def clear_people():
        command("kill @e[type=minecraft:villager]")
        wait(40)

    def settle(want, near, label, within=VILLAGE_RADIUS + 12):
        """Wait until the village standing at `near` has `want` guards.

        `within` is how far from `near` a guard may stand and still count as
        one of this village: the default is a village's own reach, but two
        villages 45 blocks apart need a tighter circle than 44 or the first
        guard of the neighbour is read as an answer here.
        """
        deadline = time.monotonic() + args.settle
        here = []
        while time.monotonic() < deadline:
            here = [g for g in frame()["guards"]
                    if math.dist(g["pos"], near) <= within]
            if len(here) >= want:
                return here
            wait(10)
        raise RuntimeError(f"{label}: {len(here)} guards within a village of it, "
                           f"{want} expected ({[g['id'] for g in here]})")

    def shot(name, at):
        ctl("look-at", str(at[0]), str(at[1]), str(at[2]))
        wait(8)
        path = OUT / f"revenge-v07-{name}.png"
        ctl("screenshot", str(path))
        say(f"screenshot {name}: {path}")
        return str(path)

    def start():
        say("launching VISIBLE window...")
        ctl("launch", "--game", game, "--world", "GuardRevengeV07", "--creative",
            "--wait", "--render-distance", "8", "--resources", args.resources,
            "--test-terrain", timeout=420)
        ctl("wait-ready", "180", timeout=210)
        ctl("options-set", "pauseOnLostFocus", "false")
        assert playing(), "game did not enter playing state"
        ctl("options-set", "tutorialStep", "none")
        ctl("key", "f1", "tap")
        command("time set day")
        command("weather clear")
        build_arena()
        goto((0, FLOOR + 1.0, 8))

    def village(near, count):
        """The guards of a village of `count` villagers that stand still.
        Counted inside 16 blocks: the neighbour village in the bystander case
        stands 45 off and its guards must not be read as an answer here."""
        return {g["id"] for g in settle(guards_for(count), near,
                                        f"the village at {near[0]}", within=16.0)}

    def ensure():
        """Back on the setup ground, still in the world.

        The chase case ends 18 blocks from the village with the whole of it
        holding a grudge; the two-village case measures distance from where its
        people were put, so it starts again from the middle of the arena.
        """
        assert playing(), "the client left the world during the chase"
        goto((A[0], FLOOR + 1.0, 8))
        heal()

    try:
        say(f"scratch home: {home}")
        start()
        protect()

        # ---- the yardstick, before anything stands here --------------------
        yard, yard_samples, yard_came, yard_id, yard_trace = monster_baseline()
        report["cases"]["monster-yardstick"] = {
            "id": yard_id, "blocks_per_tick": yard,
            "running_samples": yard_samples, "nearest": yard_came,
            "trace": yard_trace}
        baseline = yard

        # ---- one village, and who its call reaches -------------------------
        # Nine villagers that stand still, one that walks: a village of 10, so
        # the rule asks for 7 guards. The walker is summoned while the world is
        # empty of people, so naming it is a matter of reading the one id the
        # mob list reports — the nearest villager to its post would do for
        # about a minute, then it wanders and a still one is nearer.
        clear_people()
        put(WALKER_AT, 1, walker=0)
        wait(5)
        alone = {m["id"] for m in mobs()}
        put(A, 9)
        expect = guards_for(10)
        guards = {g["id"] for g in settle(expect, A, "the village")}
        walkers = [vid for vid in sorted(alone & {f["id"] for f in frame()["farmers"]})]
        assert len(walkers) == 1, \
            f"the walking villager was never alone in the world: {alone}"
        walker = walkers[0]
        report["cases"]["setup"] = {"guards": expect, "villagers": 10,
                                    "guard_ids": sorted(guards), "walker": walker}
        say(f"{expect} guards stand with the village of 10; villager {walker} walks")

        # The control: strike the one villager here that can think. That is
        # the stronger way to test it — a still one could not call anyone even
        # if the mod let it, a thinking one is the case worth ruling out.
        case = report["cases"]["villager-struck-nothing-happens"] = {}
        farmer = find(frame(), walker)
        fr = hit(farmer["id"])
        case["struck"] = fr["struck"]
        case["farmer_target"] = find(fr, farmer["id"])["target"]
        frames = watch(args.chase)
        case["guards_on_player"] = on_player(frames, guards)
        case["villagers_on_player"] = sorted(m["id"] for f in frames
                                            for m in f["farmers"]
                                            if m["target"] == "Player")
        assert case["farmer_target"] != "Player", \
            f"the struck villager itself took a target: {find(fr, farmer['id'])}"
        assert not case["villagers_on_player"], \
            f"a villager was called to arms: {case['villagers_on_player']}"
        assert not case["guards_on_player"], \
            f"striking a farmer called the guards: {case['guards_on_player']}"
        say(f"struck the walking villager {farmer['id']}: no guard took the "
            f"player in {args.chase} ticks")

        # And nothing comes of it later either.
        calm = watch(args.chase, step=8)
        case["calm_still_targetless"] = not on_player(calm, guards)
        assert case["calm_still_targetless"], \
            "a guard took the player after the villager was struck, later on"
        say(f"struck villager {farmer['id']}: no guard took the player in "
            f"{args.chase} ticks and none did after")

        # The same village, and a guard struck instead.
        case = report["cases"]["guard-struck-all-attack"] = {}
        heal()
        here = attribute_speeds()
        case["movement_speeds"] = here

        def how_many(target):
            return sum(n for v, n in here.items() if abs(v - target) < 0.005)

        # The counts are taken where the village is, not over the world. One of
        # these ten villagers has its AI on and walks, and a group standing more
        # than a village's width (32 blocks) from every other one is a village of
        # its own — `ceil(1 × 2/3) = 1`, so the hermit is guarded too. Measured:
        # a lone summoned villager in this arena gets its guard within seconds. A
        # world-wide count is therefore 7 or 8 depending on how far the walker got
        # before this line ran, which is the rule working, not a second guard for
        # the same people.
        fr = frame()
        mine = [g for g in fr["guards"] if math.dist(g["pos"], A) <= VILLAGE_RADIUS]
        own = [m for m in fr["farmers"] if math.dist(m["pos"], A) <= VILLAGE_RADIUS]
        strays = [m for m in fr["farmers"] if math.dist(m["pos"], A) > VILLAGE_RADIUS]
        case["armed_at_village"] = sorted(g["id"] for g in mine)
        case["unarmed_at_village"] = len(own)
        case["splintered"] = sorted(m["id"] for m in strays)
        assert len(mine) == expect, \
            f"{len(mine)} guards stand within a village of its people, {expect} " \
            f"expected ({sorted(g['id'] for g in mine)})"
        assert len(own) + len(strays) == 10, \
            f"{len(own)} here and {len(strays)} strays, not the ten that were " \
            f"summoned"
        # The structural half, and it holds over the whole world: the speed base
        # follows the armour, mob for mob, whoever the mob belongs to.
        assert how_many(GUARD_SPEED) == len(fr["guards"]), \
            f"{how_many(GUARD_SPEED)} villagers stand on the guard's " \
            f"{GUARD_SPEED} but {len(fr['guards'])} wear its armour: {here}"
        assert how_many(FARMER_SPEED) == len(fr["farmers"]), \
            f"{how_many(FARMER_SPEED)} on a farmer's {FARMER_SPEED} against " \
            f"{len(fr['farmers'])} unarmed: {here}"
        say(f"the village of {len(own)} has its {expect} guards in armour and in "
            f"speed; {len(strays)} villagers walked off to be a village of their "
            f"own ({case['splintered']})")
        target = reachable(guards)
        fr = hit(target["id"])
        case["struck"] = fr["struck"]
        frames = watch(20)
        case["guards_on_player"] = on_player(frames, guards)
        case["guards_total"] = len(frames[-1]["guards"])
        case["villagers_on_player"] = [m["id"] for f in frames for m in f["farmers"]
                                       if m["target"] == "Player"]
        assert len(case["guards_on_player"]) == expect, \
            f"{len(case['guards_on_player'])} of {expect} guards took the player: " \
            f"{[g['target'] for g in frames[-1]['guards']]}"
        assert not case["villagers_on_player"], \
            f"the call reached the villagers too: {case['villagers_on_player']}"
        say(f"struck guard {target['id']}: all {len(case['guards_on_player'])} "
            f"guards took the player, no villager did")

        # The chase: run 18 blocks off and see how they come. Inside the
        # 32 blocks a guard holds a grudge for, so the follow is the mod's.
        heal()
        x = round(fr["player"][0]) + 18
        goto((x, FLOOR + 1.0, 0))
        # 120 ticks rather than the 80 the other cases watch: the run-up leaves
        # this village's guards standing 4 to 25 blocks off (measured), and the
        # one 25 blocks away needs about 60 of them to cover the gap.
        frames = watch(max(args.chase, 120))
        came = closing(frames, guards)
        case["chase"] = came
        case["chase_speeds"] = speeds(frames)
        case["frames"] = frames[:3] + frames[-3:]
        assert came, f"no guard was followed: {case['chase']}"
        assert len(came) == expect, \
            f"{len(came)} of {expect} guards were followed at all"
        # The pace of the ones that came: distance taken off the gap, sample
        # by sample, while the gap was still more than five blocks. The mean
        # over all their moving is not the chase — a guard spends the rest of
        # the window swinging at you.
        pace = closing_pace(frames, guards)
        case["closing_pace"] = pace
        fastest = max(list(pace.values()) + [0.0])
        nearest = min(c["nearest"] for c in came)
        case["guard_over_monster"] = round(fastest / baseline, 2)
        # Every guard must get to bowing distance, which is what the archers
        # would not do at their goal's old 15-block range: measured standing
        # still at 13 to 16 blocks with `path None` while the sword guards were
        # already on the player. The nearest it came, not where the window found
        # it: a crossbow guard that reaches you and backs off to line a shot has
        # chased (measured: 25.3 blocks out, 5.0 nearest, 9.0 at the last frame).
        far = [c for c in came if c["nearest"] > BOW_RANGE]
        assert not far, \
            f"{len(far)} of {expect} guards never came within bow range: " \
            f"{[(c['id'], c['from'], c['nearest']) for c in far]}"
        still = [c for c in came if c["from"] - c["nearest"] < 3.0 and c["from"] > 8.0]
        assert not still, \
            f"{[c['id'] for c in still]} were called and stayed on the spot: " \
            f"{[(c['id'], c['from'], c['nearest']) for c in still]}"
        assert nearest <= 4.0, \
            f"the guards kept their distance: nearest came to {nearest} blocks " \
            f"({[c['nearest'] for c in came]})"
        assert fastest >= 1.5 * baseline, \
            f"the quickest guard closed at {fastest} blocks/tick against the " \
            f"{baseline} a monster spends coming at the player: that is not a " \
            f"chase"
        say(f"all {len(came)} guards came: every one got inside {BOW_RANGE} "
            f"blocks (nearest {nearest}), the farthest covering "
            f"{round(max(c['from'] - c['nearest'] for c in came), 1)} of them, "
            f"and the quickest took ground off at {fastest} blocks/tick, "
            f"{case['guard_over_monster']} times a monster's pace")
        # An archer's stray bolt lands on colleagues; it must not start a
        # quarrel inside the village, or the guards end up fighting each
        # other while the player walks off.
        quarrel = [g["id"] for g in frames[-1]["guards"]
                   if str(g["target"] or "").startswith("Mob(")]
        case["guard_on_guard"] = quarrel
        assert not quarrel, \
            f"{len(quarrel)} guards took each other instead of the player: " \
            f"{[g['target'] for g in frames[-1]['guards']]}"
        case["shot"] = shot("all-attack", (x - 9, 91, 0))

        # ---- two villages: the far one only watches ------------------------
        ensure()
        clear_people()
        put(A, 9)
        put(B, 9)
        a_guards = village(A, 9)
        b_guards = village(B, 9)
        each = guards_for(9)
        case = report["cases"]["bystanders-only-watch"] = {
            "each_village_guards": each, "A": sorted(a_guards), "B": sorted(b_guards)}
        heal()
        bystander = min((g for g in frame()["guards"] if g["id"] in b_guards),
                        key=lambda g: g["dist"])
        struck = reachable(a_guards)
        case["bystander_at"] = bystander["pos"]
        case["struck_at"] = struck["pos"]
        fr = hit(struck["id"])
        frames = watch(20)
        case["A_on_player"] = on_player(frames, a_guards)
        case["B_on_player"] = on_player(frames, b_guards)
        assert len(case["A_on_player"]) == each, \
            f"village A answered with {case['A_on_player']} of {each}"
        assert not case["B_on_player"], \
            f"the village 45 blocks away was called too: {case['B_on_player']}"
        say(f"village A answered with {len(case['A_on_player'])} guards; "
            f"village B, {round(math.dist(bystander['pos'], struck['pos']))} "
            f"blocks off, took nothing")

        # Now run to the ground between them: A has to chase to reach us, with
        # B standing in sight of it. Nothing strikes B, and nothing strikes A
        # again, so B can only be moved by what it sees.
        deadline = time.monotonic() + args.reach
        all_frames, arrived = [], None
        while time.monotonic() < deadline:
            goto((20, FLOOR + 1.0, 0))
            frames = watch(40)
            all_frames += frames
            near_a = [c["nearest"] for c in closing(frames, a_guards)]
            if near_a and min(near_a) <= 2.5:
                arrived = min(near_a)
                break
            heal()
        by = closing(all_frames, b_guards) if len(all_frames) > 1 else []
        case["A_arrived"] = arrived
        case["A_on_player_watched"] = on_player(all_frames, a_guards)
        case["B_on_player_watched"] = on_player(all_frames, b_guards)
        # How near village B actually stood: `closing` only reports the ones
        # that came, and the ones that never moved are the point of the case, so
        # the distance is read straight off the frames instead.
        case["bystander_nearest"] = min([g["dist"] for f in all_frames
                                         for g in f["guards"]
                                         if g["id"] in b_guards], default=None)
        case["bystander_trace"] = by
        assert arrived is not None, \
            f"no guard of village A reached the player in {args.reach}s"
        assert not case["B_on_player_watched"], \
            "a guard of the other village joined in on watching"
        near_b = case["bystander_nearest"]
        assert near_b is not None and near_b >= 12.0, \
            f"village B drifted to {near_b} blocks of the fight it was not " \
            f"called to"
        say(f"village A chased 18 blocks and swung at the player while village "
            f"B stood {near_b} blocks off, targetless")

        # Strike one of B: its own village answers now.
        heal()
        late = reachable(b_guards)
        hit(late["id"])
        frames = watch(20)
        case["B_after_struck"] = on_player(frames, b_guards)
        assert len(case["B_after_struck"]) == each, \
            f"struck, B answered with {case['B_after_struck']} of {each}"
        say(f"struck one of B and all {len(case['B_after_struck'])} of them came")
        case["shot"] = shot("two-villages", (24, 91, 0))
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        say(f"FAILED: {exc}")
        raise
    finally:
        (OUT / "revenge-v07-report.json").write_text(json.dumps(report, indent=2),
                                                     encoding="utf-8")
        try:
            ctl("quit", timeout=90)
        except Exception as exc:
            say(f"quit: {exc}")
        log.close()


if __name__ == "__main__":
    main()
