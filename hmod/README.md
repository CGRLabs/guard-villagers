# Guard Villagers — WebAssembly `.hmod`

This directory is the 0.8.0 port of Guard Villagers to Horizon's sandboxed mod API. The old
`.hnmod` mixin tree at the repository root remains for history; this is the installable build.

- **id:** `guard_villagers`
- **kind:** WebAssembly (`mod`, side `both`)
- **SDK:** `0b14f8acfd97fa2c750e42795249dcc981178ca4`
- **Toolchain:** Rust 1.99.1, target `wasm32-wasip1`

## Behaviour

On each server-side level tick the mod surveys villagers, groups nearby villagers into villages,
and hires `ceil(regular * 2 / 3)` guards per village. Guards are persistent entities marked with a
mod-owned tag; they are equipped with iron armour and an iron sword, shield or crossbow, and get
melee, hurt-by-target and nearest-hostile goals. Babies born near guards are converted into guards
when the village is short, surplus guards lend to a neighbouring village before new hires happen,
and attacking one guard alerts the rest.

The village rules are host-free in `src/rules.rs` and covered by unit tests. `src/server.rs` is the
thin adapter to Horizon handles, goals, equipment and item keys.

## Build and check

```sh
cd hmod
RUSTUP_TOOLCHAIN=1.99.1 cargo test
cargo horizon-mod build --wasm
RUSTUP_TOOLCHAIN=1.99.1 cargo horizon-mod check
cargo horizon-mod check target/horizon-mod/guard_villagers.hmod --json
```

The repository root pins an older toolchain for the legacy `.hnmod` tree, so set
`RUSTUP_TOOLCHAIN=1.99.1` when running plain Cargo or the source check from `hmod/`.
`cargo horizon-mod build --wasm` selects the pinned toolchain itself and also generates
`mod.wasm`, which is a build artifact and is not committed.

The checked 0.8.0 package has SHA-256
`afc6c5aa0543c1f965fcf1d075fce388af47774c6b04cf86fd7229e9121202b2`.
