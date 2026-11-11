# Guard Villagers — design decision (2026-11-11)

## The decision

**Guards are ADDED to a village. They do not replace its villagers.**

A village with 8 villagers keeps its 8 — every one of them keeps its profession, its trade and
its vanilla behaviour. The mod then adds a few **extra** villagers as guards, so the population
becomes:

```
regular + workers  +  guards
```

The earlier design (v0.4/v0.5) **converted** every adult villager into a guard: everyone got a
sword, a shield or a crossbow, iron armour, combat goals and a guard skin. That is wrong — it
destroys the village. Farmers stop farming, blacksmiths stop smithing, and the village stops
being a village.

## The rule the user settled on (2026-11-11)

- **Two guards for every three villagers.** `guards = ceil(regular × 2/3)` — four per six,
  six per eight.
- **The guards are extra, on top.** A village of eight keeps its eight farmers, smiths and
  traders and gains six guards: fourteen people, not six.
- **The count follows the village.** A village that grows gets more guards; the ratio is
  recomputed from the villagers it has.
- **A baby born next to a guard grows up into one.** The baby is an ordinary villager while
  it is small; when it becomes an adult, if it was born next to a guard, it is armed like
  one. A baby born away from the guards grows up an ordinary villager.
- **A village keeps its villagers' lives.** No villager is converted: no villager loses its
  profession, its trade or its work.

## What this costs, and why it is not a small change

The mod today is **client-only**. It edits the client's copy of each villager. That works for
*changing* a villager you can already see.

**Adding** a villager is different: a villager only exists if the world that simulates it says so.
Horizon's native-mod API has exactly the right tool for it, but it is a **server-side** one:

| Hook | API | What it does | Server-side? |
| --- | --- | --- | --- |
| `native_spawn_mob(dim, kind, pos, &NativeSpawn)` | 37 | spawns a mob in the level in place, returns its id | **yes** |
| `native_mobs(dim)` | 37 | lists the living mobs: id, kind, pos, yaw, health | **yes** |
| `native_remove_mob` / `native_kill_mob` | 37 | takes one away / kills it | **yes** |
| `native_run_command(line)` | 21 | runs a console command (level 4) — `/summon` with full NBT | **yes** |
| `native_net_send_to_player` / `native_net_from_server` | 40 | server → client messages | both halves |

Source: `crates/horizon-client/src/game/native_mobs.rs`, `game/native_server.rs`,
`game/native_net.rs`. Docs: `docs/native-mods.md` ("Mobs", "Mod messages", "Multiplayer").

### The consequence you have to know about

From `docs/native-mods.md`, "Multiplayer":

- **Single player and LAN host** — the bundle runs in the host's game *and* its integrated
  server, so the server half works and every player of the world sees the guards. ✅
- **Joining someone else's server** — only client-side hooks do anything. The guards would not
  appear. ❌
- **Dedicated servers** — native mods are not built for them yet. ❌

So: **the guards appear in single player and on a LAN host, and nowhere else.** For a mod whose
whole point is village defence, that is a real limitation, but it is the API's limit today, not
ours.

## The three things the new design must solve that the old one got for free

**1. Which villagers are guards?**
The client cannot read a mob's NBT tags — the client `Mob` struct has no tags field
(`crates/horizon-client/src/mobs.rs`). The server helper cannot read equipment either
(`native_mobs` returns id/kind/pos/yaw/health only). So "is this villager a guard?" needs a
channel. Options, best first:
  - **mod messages (API 40)** — the server half sends the new guard's id to each player over the
    `guard_villagers:guards` channel; the client half marks it. Clean, no visual artefact.
  - the server spawns guards with a custom name (`NativeSpawn.name`) and the client matches on
    it — works, but floats a "Guard" nametag over every guard.
  - the client guesses from the held item — fragile.

**2. How does a guard get its sword?**
`NativeSpawn` has no equipment field: name, health, `no_ai`, `invisible`, `silent`, `invulnerable`,
`no_gravity` — that is all. Two routes:
  - `native_run_command("/summon minecraft:villager ... {equipment:{...}, Tags:[...]}")` — full
    NBT control, **but** `native_run_command` refuses unless a **LAN host is open**
    (`game/native_server.rs:339`: `if self.lan_acting.is_some() || self.lan.is_none() { return false }`),
    so it does not work in plain single player.
  - `native_spawn_mob` — works in single player, but the mob comes out plain.

**3. How does a guard fight on the server?**
There is no "make this mob attack that mob" hook. The current mod's damage is client-side
(`MobEvent::AttackMob` in the mob's outbox). Server-side damage is possible through the console:
`/damage <target> <amount> done by <guard>` gives the guard credit — but only via
`native_run_command`, with the LAN-host caveat above.

## Finding the villages

Villagers carry their village's POIs as memories — `home`, `bed`, `meeting`
(`m.extra.home`, `m.extra.bed`, `m.extra.meeting`;
`crates/horizon-client/src/game/creatures.rs:950` lists them under `"pois"`), and
`villager_brain::poi_at(w, x, y, z)` reads a POI (`crates/horizon-client/src/mobs/villager_brain.rs:822`).
Group villagers by the point they claimed and each group is a piece of a real village.

That was the whole rule here until the first run in a generated village, and it is not enough: the
people of one village claim *different* points — everyone has their own bed — so the groups come out
one villager wide. The shipped rule keeps the POI grouping and then folds groups that stand within
`VILLAGE_RADIUS` of each other into one village. See *What the real village found*.

## Target numbers (to decide)

Open questions for the design, not settled yet:
- do the guards have a profession (armorer?) and a name?
- do the guards ever leave, or are they permanent additions?

## How it is built (v0.6.0, 2026-11-11)

Two support modules, because the two halves live in different crates:

| Module | Declared in | Crate | What it holds |
| --- | --- | --- | --- |
| `guard_villagers` (`runtime.rs`) | `crates/horizon-client/src/client_lib.rs:187` | `horizon-client-lib` (its lib root is that file) | the shared logic: the ratio, the roles, the guard marker, the skins |
| `guard_villagers_server` (`server.rs`) | `crates/horizon-client/src/game.rs:12646` | `horizon-client` | the server half: the villages, the spawning, the arming, the strikes |

Two crates, so two `cargo test` runs: `-p horizon-client --lib` alone never sees the four tests in
`runtime.rs`.

The library cannot see the `Game`, and the game cannot be reached from the library, so the
server half needs its own module in the game crate. A helper file holds exactly one function
(the mixin CLI requires it), so the helper is a one-liner that calls into the server module.

**The guard marker is its equipment**: iron armour and a sword or a crossbow. The server gives
every guard exactly that, and it survives a restart — so a guard is a guard on every machine,
with no bookkeeping and no messages between the halves.

**The two halves share the guard list.** The library's statics are one copy per process, and in
single player the client window and the integrated server are two threads of one process: the
server half writes the guard ids into `guard_villagers::GUARDS`, and the client half of the same
world reads them. So the player sees the armour and the weapon even where the world does not
send them — which it does not: the client half arms its own copy of the guard.

**The village is where its villagers stand.** A villager's `home`, `bed` and `meeting` memories
(`m.extra.home`, `m.extra.bed`, `m.extra.meeting`) group it with the neighbours that claimed the
same point; villagers who claimed none join the nearest group, or stand together in one of their
own; and groups whose people are within `VILLAGE_RADIUS` (32 blocks) of each other are folded into
one village. The last step is what makes a generated village count once — see *What the real village
found*.

**A guard belongs to the village it remembers, not the one it happens to stand near.** Guards chase
and walk; measured ones get 40+ blocks from their village's centre. Counting a guard by distance
alone makes it belong to no village, so the village thinks it is short of a guard and spawns
another, without end. Each guard's remembered key is looked up first (`village_for`), the nearest
village is only a fallback, and a folded village keeps a name that does not depend on mob order —
otherwise the key it stores and the key it later looks up are different villages.

**The server half runs where the world is simulated.** `native_level_tick_post` only fires
there: `observe_level = running.is_some() && (serving.is_some() || options.dedicated.is_some())`
(`crates/horizon-client/src/game/levels.rs:384`), and "LAN is an integrated server". So the
guards are added in single player and on a LAN host, and nowhere else.

### What the first proof run found

The v0.6.0 build that armed the guards on the server alone passed the count but failed twice,
and both failures were about the same thing — **the client never saw the guards**:

- The marker required the weapon *in hand*. A villager that lost it counted as a regular
  villager, so the village kept adding guards: 41 of them for 4 villagers. The marker is now
  the armour, which does not wander off.
- The server's equipment does not reach the client (`mob_equipment` fills the entity state and
  `send_equipment` sends what changed — but the client showed no weapon at all). The client
  half now arms its own copy of the guard, which is what the old design did too: the old mod
  was client-side all along, and the server never had a sword either.

### The proof that passed (2026-11-11)

`tools/proof_village.py`, a village of six summoned villagers on flat ground, and two husks for
the guards to fight:

| Check | Result |
| --- | --- |
| The village's villagers | 6, **none of them armed**, professions unchanged |
| The guards added | **4** — `ceil(6 × 2/3)`, the rule the user set |
| The guards' armour | 4 villagers wearing the iron chestplate, and the same 4 holding a sword or a crossbow |
| A baby born next to a guard | grew up **holding a crossbow** |
| The sword guard, at a husk | `MeleeAttack` running, target `Mob(15)`, **2.0 blocks** away, husk 20.0 → 17.06 hp (**2.94 damage**, the mod's 3.0 per swing) |
| The crossbow guard, at a husk | `CrossbowAttack` running, target `Mob(19)`, **3.80 blocks** away — outside the 2.5-block melee reach — with a projectile of kind `Arrow` in the air, husk 20.0 → 16.06 hp (**3.94 damage**) |
| Nobody else was armed | 0 other guards alive in the world at either hit |

Report: `target/proof/village-v06-report-green.json` → `passed: true`. The screenshots
(`village-v06-village.png`, `village-v06-guard.png`, `village-v06-grown-guard.png`,
`village-v06-melee-combat.png`, `village-v06-crossbow-combat.png`) show the farmers in their straw
hats with the guards beside them, and each guard on its husk.

Note: the `entities` command of the control API has **no** `held` field — the `mobs` command has
it (`creatures.rs:480`), and that is what the proof reads.

Measuring combat took four attempts, and each failure was a fact about the control API rather than
about the mod:

- `ctl tp` moves only the **client's** copy of the player. The world loads and ticks its chunks
  around the *server's* player, and `mobs` measures from the client's position, so a test away
  from the spawn point needed the game's own `tp @a x y z` as well.
- A bolt lives a few ticks in the air, so "was there an arrow" cannot be sampled once per poll.
  The proof therefore stands on the goal the mod put on the guard (`MeleeAttack`,
  `CrossbowAttack` — a vanilla villager runs neither), the measured distance, and the fact that
  nothing else armed existed, and records the bolts it happens to see.
- A corpse stays in the mob list at 0 hp, so the dummy is tracked by the id the summon returned,
  not by its kind.
- `hurtlog` covers players only, so it cannot attribute damage to a mob.

### What the real village found (2026-11-11)

`tools/proof_real_village.py` starts a normal world (seed `20261111`), locates the nearest village
with the game's own `locate structure #minecraft:village`, drops the player onto it and reads the
population. Its first run failed with something the flat-ground proof could not show:

    the world's village: -928 -432      (a taiga village)
    the village's own villagers: 4, guards added: 5

Those four villagers had claimed **four different points** — a bed here, a job site there, the
meeting point — and grouping purely by the claimed point saw four villages of one. Each of them is
short of `ceil(1 × 2/3)` = one guard, so the village got four, and the fifth came from the guards
being re-attributed between those overlapping one-villager villages as their centres moved. The
rule the user set (two guards per three villagers) asks for three there, and in a village of a dozen
it would have asked for eight rather than twelve.

The grouping now folds neighbouring groups together (`merge_neighbours` in `server.rs`), so a
village is the villagers who stand within `VILLAGE_RADIUS` of each other whatever point each
claimed, and the count is made once for the whole of it.

The second run of the same proof, on a plains village, failed differently:

    the world's village: -400 100      (a plains village)
    the village's own villagers: 13, guards added: 23

Thirteen villagers are short of 9 guards, and the fold had made them one village (groups of 8, 2,
2, 1 by claimed point, all inside the radius). The extra guards were **recruited every tick**:
attribution asked only whether a guard stood within `VILLAGE_RADIUS` of a village centre, and the
village's own guards do not stay there — one of them was measured 42.7 blocks from the nearest
centre and 35 blocks below it, having walked down to whatever it was chasing. A guard counted
nowhere is a guard the village is short of, so it spawned another, and the population grew without
end (entity ids 238…321 appearing long after 36…89).

Two things fix that, both in `server.rs`:

- **Attribution by memory, not by distance.** Each guard keeps its village's key (`village_for`);
  the key is looked up first and only when that village is gone does the guard fall back to the
  nearest one — with no radius cap, because a guard that wandered off still belongs to the village
  it came from.
- **A village keeps one name.** The fold used to leave the merged village named for whichever
  group happened to come first in the mob list, so the same cluster had a different key from tick
  to tick and the guards' remembered keys never matched. `Village` now carries whether its key is a
  point a villager claimed or the ground its villagers stand on, and `absorb` keeps the lower key
  of the two, claimed points beating standing ground. The name is then stable and a guard that
  walked to its bed is still recognised (`a_guard_that_walked_to_its_bed_still_belongs_to_its_village`).

Both proofs are green on the rebuilt client (2026-11-11, 23:14 and 23:20):

| Proof | What it measured | Result |
| --- | --- | --- |
| `tools/proof_village.py` (flat ground, deterministic) | 6 villagers → 4 guards, villagers still unarmed, a baby next to a guard grown into one, 2.94 melee damage at 2.0 blocks, 3.936 crossbow damage at 3.8 blocks with one `Arrow` in the air | pass |
| `tools/proof_real_village.py` run A (taiga `-928 -432`) | 4 villagers seen as 1 group of 4 → 3 guards, professions unchanged, 3 iron chestplates for 3 guards | pass (was 5 guards) |
| the same, run B | 4 villagers seen as 2 groups (1 + 3) → 1 + 2 = 3 guards, same assertions | pass |

Run A and run B differ because the villagers had walked differently between the runs, which is the point
of the fold: whether the census sees one group or two within 32 blocks, the village gets the guards the
rule asks for and no more.

### The unit tests (2026-11-11)

`python tools/horizon.py test` runs both crates the mod lives in, in the `fast` profile:

| Crate | Module | Tests | Result |
| --- | --- | --- | --- |
| `horizon-client-lib` (its lib root is `client_lib.rs`, where `runtime.rs` is injected) | `guard_villagers::tests` | the ratio (`guards_for`), the three loadouts, re-arming without unloading a charged crossbow, every role mapping to a supplied skin | **4 passed** |
| `horizon-client` (`game.rs`, where `server.rs` is injected) | `guard_villagers_server::tests` | four neighbours that claimed four different points fold into one village short of 3 guards; two groups 200 blocks apart stay two villages of one guard each; a village keeps its name whatever order the mobs come in; a guard that walked to its bed still belongs to its village | **4 passed** |

Before this the harness asked `cargo test` for `--bin horizon-client` turned into `--lib`, which left
the binary's name in the test-name slot and made the real filter a second positional argument — cargo
rejected the whole command, so no unit test of this mod had ever run. It took two crates because the
mod's two halves are in two crates.

### What the proof does not cover yet

- A **LAN guest** (a second process) has its own copy of the library's statics, so it does not
  share the guard list; it would need the equipment to come from the server instead.
- Guards' health in the generated village: two of the five were at 17 and 18 hp with nothing hostile
  within reach on peaceful difficulty. Fall damage from the spawn point is the likely cause and it
  has not been measured.

## What the code looks like now (v0.5, 2026-11-10)

Proof green: `tools/proof_gear.py` → `target/proof/gear-v05-report.json` (`passed: true`),
unit tests 3/3. It converts, so **all of this is to be rewritten**, not extended:

| File | Today | Has to become |
| --- | --- | --- |
| `guard_helper.rs` | equips + arms **every** adult villager, runs the melee pass | server half: find villages, spawn the missing guards. client half: only the marked guards |
| `render_helper.rs` | swaps **every** villager's model for the guard model | only the marked guards |
| `body_helper.rs` | draws the guard skin for the guard model | unchanged, but only marked villagers ever have that model |
| `equipment_helper.rs` | keeps the weapons on every villager | only the guards |
| `brain_helper.rs` | stops the villager brain panicking so they fight | only the guards |
| `arms_helper.rs`, `held_helper.rs`, `items_helper.rs` | poses and held items | unchanged |
| `layers_helper.rs` | drops the vanilla overlay layers for guards | unchanged |
| `runtime.rs` | role by mob id, skins, loadouts | gains: village grouping, the guard set, the spawn bookkeeping |

`compatibility.json` will need `"hooks": 40` (mod messages) or `37` (mobs only) instead of nothing —
it is currently revision-pinned with no `hooks` field.
