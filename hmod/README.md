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
cargo test
cargo horizon-mod check
cargo horizon-mod build --wasm
cargo horizon-mod check target/horizon-mod/guard_villagers.hmod --json
```

The checked 0.8.0 package has SHA-256
`d6c9c891e7da3d7cb1bbf758d9ea274d3459a2d3a0f7f02ebb2e9db3bcc0682a`.
