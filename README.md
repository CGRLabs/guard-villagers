# Guard Villagers

**A village that can defend itself — without stopping being a village.**

Every village the game generates keeps its own people. The farmer farms, the librarian shelves books,
the toolsmith hammers, and none of them is handed a sword. On top of them the mod adds **guards**: extra
villagers, two for every three the village already has, who wear iron armour, carry an iron sword and a
shield or a crossbow, and walk up to whatever is hurting the village and hit it. A baby born next to a
guard grows up to be one; a baby born anywhere else grows up ordinary.

Watch a village at night: the guards are the ones standing at the edge of the torchlight, and when a
zombie comes over the hill they go to it instead of running.

The rule is the whole design: **guards are added, villagers are never converted.** A village of eight keeps
its eight and gains six guards — fourteen people, not six that forget their jobs.

## What a guard is

| | |
|---|---|
| How many | `ceil(villagers × 2/3)` per village, recomputed as the village grows |
| What they wear | a full set of iron armour — that armour is also how the guard is recognised |
| What they carry | an iron sword and a shield, just an iron sword, or a crossbow (about one in three is the archer) |
| What they fight | the hostile mobs that come near: zombies, husks, skeletons, spiders, creepers, vindicators and the rest |
| Where they stand | beside their village's own villagers, by the beds, the bell and the job sites |
| When they stop | they go back to standing their post once the thing they were fighting is gone |

Nothing to bind, nothing to configure. **Options > Mods** has one row that says it is installed.

## Play it

**Through the Horizon launcher** (the usual way for a native mod): Mods → **Add from GitHub** →
`https://github.com/CGRLabs/guard-villagers`, then Settings → Game → **Native mods (experimental)** →
**Build**. The launcher downloads its own Rust and compiles the mod into a game of your own; the first
build takes 20 to 30 minutes, later ones are incremental. Its `.hnmod` asks for hook points v37, so it
builds on any Horizon that has them rather than one exact commit. Most of what it touches are Horizon's
own private functions, though — villager rendering, the held-item draw, the villager brain, the level
tick — so when Horizon moves one of those the bundle needs the new path, and we publish it as a new
version.

Native mods are unsandboxed code that runs with your rights, and this one is not reviewed by the Horizon
registry — the launcher will say so in red before it builds. The bundle is fifteen small `.rs` files under
`mixins/guard_villagers/`; read them first.

**Without the launcher:** `horizon-client-guard.exe` ships with
[release v0.6.0](https://github.com/CGRLabs/guard-villagers/releases/tag/v0.6.0): a Horizon client with
Guard Villagers already compiled in. Drop it into a prepared Horizon 26.3 folder (one where
`horizon-prepare` has run) and start it in place of `horizon-client`. It is built for commit `e14b35ce`
(the 2026-11-11 Nightly), so it will not match an older install — for another Nightly, use the launcher
build above.

Either way, to see it fast: find a village (`/locate structure #minecraft:village`), make it night
(`/time set night`) and stand back. Within about a minute the guards walk up beside the villagers. To
count them yourself: `/data get entity @e[type=minecraft:villager,limit=1] equipment`.

## Getting it running

Guards are **added to the world**, not painted onto the client: they are real villagers with real armour,
so they take damage, they can die, and a village that loses people gets fewer guards. That means the half
of the mod that makes them has to run where the world is simulated:

- **Single player**: works, this is what every screenshot here comes from.
- **You as the host of a LAN or server game**: works, the guards are the host's.
- **Joining someone else's game**: you see their guards — the armour and the weapon sync, and the client
  half dresses each guard it can see — but the guest's own list of guards is its own, so a guard the host
  has not armed yet can look unarmed for a moment. Multiplayer has not been stress-tested yet.
- **Babes, golems and raids**: the mod does not touch iron golems, does not stop villagers breeding, and
  does not change what a villager trades.

## For developers

### The two halves

| Half | Lives in | What it does |
| --- | --- | --- |
| server | `mixins/guard_villagers/server.rs`, injected into `crates/horizon-client/src/game.rs` | finds the villages, counts their villagers, spawns the guards they are short of, arms them, gives them their goals, and swings their swords |
| client | `mixins/guard_villagers/runtime.rs`, injected into `crates/horizon-client/src/client_lib.rs` | marks which villager is a guard, dresses it in the guard model and one of the four skins, poses its arms, holds its weapon, and stops the vanilla brain from panicking over the guard's own combat target |

A village is where its villagers stand. They are grouped by what each claimed — a home, a bed or a
meeting point — and groups whose people are within 32 blocks of each other are then folded into one: the
world gives every villager its own bed, so claiming alone would see one village per villager. A group of
villagers that claimed nothing joins the nearest, or stands together as one of its own, which is what makes
a hand-built farm count as a village too.

Guard-ness is marked by the armour, not by a side table: the server gives every guard a full iron set, so a
guard reads as a guard on every machine that can see the entity, and survives a restart and a world the mod
did not create. The control API shows the helmet of that set as the mob's `head`.

### What it injects

Twelve injections, all in `mixins/guard_villagers/horizon-mixin.toml`:

| Target | Why |
| --- | --- |
| `game::native_hooks::Game::native_level_tick_post` | the server half: villages, spawns, equipment, the melee pass |
| `game::native_hooks::Game::native_frame` | the client half: gives a guard its model |
| `game::native_hooks::Game::native_mods` | the row in Options > Mods |
| `mobs::render::body`, `mobs::render::layers` | the guard skin instead of the villager robe, and no overlay layers |
| `mobs::render::held_item_transform`, `game::mob_blocks::Game::held_item_geometry` | the weapon in the right hand, drawn as an item, not a villager's empty hand |
| `mobs::villager::anim` | uncrossed arms, the crossbow charge pose |
| `mobs::villager_brain::tick`, `mobs::villager_brain::sync` | the guard keeps its combat target instead of the brain forgetting it |
| `mobs::data::MobData::load` | loads the player-format model once, for the guard bodies |
| `horizon_client_render::hud::HudAtlas::slots` | puts the four skins into the texture atlas |

### The skins

`assets/minecraft/textures/entity/guard_villagers/` holds four 64×64 player-format skins. They are
embedded in the bundle as byte literals (`mixins/guard_villagers/skins.rs`) and appended to the HUD atlas,
so there is no separate resource pack: one mod, one download. Regenerate `skins.rs` only with
`python tools/gen_guard_skin.py` (it has a `--check` mode, and the output must be reproducible).

### Build, prove, package

```
HORIZON_MIXINS=/path/to/horizon-mixins python tools/horizon.py build --horizon /path/to/horizon
HORIZON_MIXINS=/path/to/horizon-mixins python tools/horizon.py test --horizon /path/to/horizon
python tools/proof_village.py --game <abs path to target/horizon-cargo/fast/horizon-client.exe>
python tools/proof_real_village.py --game <same>
python tools/package.py --check-hooks      # -> target/guard_villagers-<version>.hnmod
```

`horizon.py test` runs both modules' unit tests (`guard_villagers::tests` for the ratio, the roles and the
skins; `guard_villagers_server::tests` for the village grouping) in the same `fast` profile as the build, so
it reuses its artifacts. On Windows the mixin CLI cannot replace a generated stage in place
(`E_ATOMIC_STAGE`), so move `target/mixins/modded` aside after changing anything under `mixins/`, and expect
the whole workspace to recompile once.

`tools/proof_village.py` is the deterministic check (a village of six on flat ground: its six villagers are
still unarmed, four guards appear, nobody's profession changes, a baby next to a guard grows into one, and
a sword and a crossbow each do measurable damage to a husk). `tools/proof_real_village.py` runs the same
promise against a village the world generated from a fixed seed. `DESIGN.md` records why the design changed
and what each proof covers; `compatibility.json` holds the pins.

### Tests

`python tools/horizon.py test` runs the unit tests of both halves: `runtime.rs` (skins, loadouts, the
two-per-three rule, re-arming a guard that lost a weapon without unloading its crossbow) and
`server.rs` (the village grouping: neighbours that claimed different points are one village, groups far
apart stay apart, a village keeps the same name whatever order the mobs come in, and a guard that walked
to its bed still belongs to the village it came from).

## Not a port

Village guards are an old idea in the Minecraft community, and the name says what they are. This is an
original implementation for Horizon with its own rule — guards are *added*, `ceil(villagers × 2/3)` of
them, never converted from the villagers a village already has — and it holds no code, assets or data
from any Java Edition mod.

## Licence

MIT. Not an official Minecraft product; not approved by or associated with Mojang or Microsoft. Horizon is
a Rust rewrite of Minecraft: Java Edition 26.3 by Ludovic Marie and contributors — this is a mod for it,
and it contains no Minecraft code or assets.
