//! Guard Villagers — every village gains extra guards, added on top of the
//! farmers, smiths and traders it already had.
//!
//! Ported from the retired native `.hnmod` to a sandboxed wasm `.hmod`. The
//! villager grouping rules live in `rules` (pure, unit-tested); `server` drives
//! them from the authoritative level through the mod API's handles.

mod rules;
mod server;

pub use server::GuardMod;
