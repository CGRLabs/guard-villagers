//! The server half of Guard Villagers, written against the new mod API.
//!
//! It runs on the authoritative level (`level_tick_post`, server side only).
//! The retired `.hnmod` reached into `Game`'s private mob list and edited it in
//! place. Here the world is reached through handles, and guard identity is kept
//! on the entity itself as a tag — so it survives a reload and needs no global
//! mutable state in the sandboxed guest.

use mod_api::{
    self, EntityRef, EquipmentSlot, GoalSpec, Hooks, HostSide, ItemKey, ItemStack,
    LevelTickPostEvent, LivingRef, MobFilter, MobRef, Registrar, RegistrationContext, SpawnReason,
};
use std::sync::OnceLock;

use crate::rules::{self, Villager};

/// Item keys are resolved once at registration, then reused every tick.
static ITEMS: OnceLock<Items> = OnceLock::new();
struct Items {
    sword: ItemKey,
    shield: ItemKey,
    crossbow: ItemKey,
    helmet: ItemKey,
    chestplate: ItemKey,
    leggings: ItemKey,
    boots: ItemKey,
}

/// The hostile species a guard hunts. Vanilla's villager already flees these;
/// the guard's target goal makes it close instead. Creepers are deliberately
/// left out, as in the original: a guard that charges a creeper loses a village.
fn hostile_species() -> Vec<String> {
    [
        "minecraft:zombie", "minecraft:husk", "minecraft:zombie_villager",
        "minecraft:skeleton", "minecraft:stray", "minecraft:wither_skeleton",
        "minecraft:spider", "minecraft:cave_spider", "minecraft:enderman",
        "minecraft:witch", "minecraft:vindicator", "minecraft:evoker",
        "minecraft:pillager", "minecraft:ravager", "minecraft:zoglin",
        "minecraft:piglin", "minecraft:piglin_brute", "minecraft:drowned",
        "minecraft:phantom", "minecraft:slime", "minecraft:mage",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

/// A mob as the grouping rules see it.
#[derive(Clone, Copy)]
struct Seen {
    villager: Villager,
    entity: EntityRef,
    guard: bool,
    baby: bool,
    alive: bool,
    /// The village point remembered on the entity as tags `gv:p:`, `gv:q:`, `gv:r:`.
    remembered: Option<[i32; 3]>,
}

fn remembered_key(host: &dyn mod_api::Host, e: EntityRef) -> Option<[i32; 3]> {
    let tags = e.tags(host)?;
    rules::remembered_from_tags(tags.iter().map(String::as_str))
}

/// Take one snapshot of the level's living population through handles.
fn survey(host: &dyn mod_api::Host, level: mod_api::LevelRef) -> Vec<Seen> {
    let Some(entities) = level.all_entities(host) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for e in entities {
        let kind = e.kind(host).map(|k| k.id(host));
        let Some(kind) = kind else { continue };
        if kind != "minecraft:villager" {
            continue;
        }
        let Some(pos) = e.position(host) else { continue };
        let Some(living): Option<LivingRef> = host.living(e) else { continue };
        let baby = living.baby(host).unwrap_or(false);
        let alive = living.health(host).unwrap_or(0.0) > 0.0;
        let tags = e.tags(host).unwrap_or_default();
        let guard = tags.iter().any(|t| t == rules::GUARD_TAG);
        // A claimed bed / home / meeting is not exposed as a handle read in the
        // mod API, so villages are found from where villagers stand. The rules'
        // proximity grouping is the same path the original used for hand-built
        // farms, and handles generated villages too (0.7.1, five seeds).
        let key = remembered_key(host, e);
        let villager = Villager { id: e.id(), key, pos };
        out.push(Seen { villager, entity: e, guard, baby, alive, remembered: key });
    }
    out
}

/// Give a new guard its kit: armour, weapon, speed, reach, and combat goals.
fn arm(host: &mut dyn mod_api::ServerHost, items: &Items, s: &Seen) {
    let id = s.villager.id;
    let Some(living): Option<LivingRef> = host.living(s.entity) else { return };
    let (_, main, off) = rules::loadout(id);

    let armor = [
        (EquipmentSlot::Head, items.helmet),
        (EquipmentSlot::Chest, items.chestplate),
        (EquipmentSlot::Legs, items.leggings),
        (EquipmentSlot::Feet, items.boots),
        (EquipmentSlot::MainHand, if main == rules::CROSSBOW { items.crossbow } else { items.sword }),
    ];
    for (slot, key) in armor {
        if living.equipment(host, slot).is_none() {
            let _ = living.set_equipment(host, slot, ItemStack::new(key, 1));
        }
    }
    if off == Some(rules::SHIELD) && living.equipment(host, EquipmentSlot::OffHand).is_none() {
        let _ = living.set_equipment(host, EquipmentSlot::OffHand, ItemStack::new(items.shield, 1));
    }

    // A guard outruns a farmer and can see across its village. The modifier is
    // permanent and unique by id, so re-arming never stacks it.
    let speed = mod_api::AttributeModifier::new(
        mod_api::Identifier::parse("guard_villagers:speed").unwrap(),
        rules::GUARD_SPEED,
        mod_api::AttributeOperation::AddValue,
    );
    let _ = living.add_attribute_modifier(
        host, "minecraft:movement_speed", speed, mod_api::ModifierLifetime::Permanent,
    );
    let reach = mod_api::AttributeModifier::new(
        mod_api::Identifier::parse("guard_villagers:reach").unwrap(),
        rules::VILLAGE_RADIUS,
        mod_api::AttributeOperation::AddValue,
    );
    let _ = living.add_attribute_modifier(
        host, "minecraft:follow_range", reach, mod_api::ModifierLifetime::Permanent,
    );

    let Some(mob): Option<MobRef> = host.mob(s.entity) else { return };
    // `add_goal` appends to the selector; it does not replace a goal of the
    // same kind. Adding these every tick would give a loaded village two more
    // goal objects per guard per tick, without bound, so read the selectors
    // back and install only what is missing. A chunk reload rebuilds the
    // selectors, so a reloaded guard reads back missing and is armed again.
    let Some(goals) = mob.goals(host) else { return };
    let Some(targets) = mob.target_goals(host) else { return };
    let goal_ids: Vec<&str> = goals.iter().map(|g| g.id).collect();
    let target_ids: Vec<&str> = targets.iter().map(|g| g.id).collect();
    let missing = rules::missing_goals(&goal_ids, &target_ids);

    if missing.melee {
        let _ = mob.add_goal(host, 1, &GoalSpec::MeleeAttack {
            speed: rules::CHASE_SPEED,
            follow_unseen: true,
        });
    }
    if missing.hurt_by_target {
        let _ = mob.add_target_goal(host, 1, &GoalSpec::HurtByTarget { alert: true });
    }
    if missing.nearest_target {
        let _ = mob.add_target_goal(host, 2, &GoalSpec::NearestTarget {
            prey: MobFilter::Species(hostile_species()),
            must_see: false,
            must_reach: false,
            interval: 5,
        });
    }
}

fn remember_village(host: &mut dyn mod_api::ServerHost, e: EntityRef, key: [i32; 3]) {
    // Drop every axis tag the guard already carries, not one sentinel value:
    // a guard that walks between villages would otherwise keep the old
    // coordinates beside the new ones and read back as a mixed key.
    let stale: Vec<String> = e
        .tags(host)
        .unwrap_or_default()
        .into_iter()
        .filter(|t| rules::is_key_tag(t))
        .collect();
    for t in stale {
        let _ = e.remove_tag(host, &t);
    }
    for (prefix, value) in rules::KEY_PREFIXES.into_iter().zip(key) {
        let _ = e.add_tag(host, &format!("{prefix}{value}"));
    }
}

/// One authoritative level tick: keep guards armed, settle babies, count the
/// villages and add the guards they are short of.
fn tick(host: &mut dyn mod_api::ServerHost, level: mod_api::LevelRef) {
    let Some(items) = ITEMS.get() else { return };
    let seen = survey(host, level);

    // Discover guards and re-arm the ones already carrying the marker.
    for s in seen.iter().filter(|s| s.guard && s.alive && !s.baby) {
        arm(host, items, s);
    }

    // A baby born near a guard grows into one.
    let guards_near: Vec<[f64; 3]> = seen
        .iter()
        .filter(|s| s.guard && s.alive)
        .map(|s| s.villager.pos)
        .collect();
    for s in seen.iter().filter(|s| !s.guard && s.baby && s.alive) {
        let near = guards_near
            .iter()
            .any(|p| rules::distance(*p, s.villager.pos) <= rules::BREED_RADIUS);
        if near && !s.entity.tags(host).unwrap_or_default().iter().any(|t| t == "gv:heir") {
            let _ = s.entity.add_tag(host, "gv:heir");
        }
    }
    for s in seen.iter().filter(|s| !s.baby && !s.guard && s.alive) {
        if s.entity.tags(host).unwrap_or_default().iter().any(|t| t == "gv:heir") {
            let _ = s.entity.add_tag(host, rules::GUARD_TAG);
            let _ = s.entity.remove_tag(host, "gv:heir");
            arm(host, items, s);
        }
    }

    // Count the villages.
    let regular: Vec<Villager> = seen
        .iter()
        .filter(|s| !s.guard && !s.baby && s.alive)
        .map(|s| s.villager)
        .collect();
    if regular.is_empty() {
        return;
    }
    let guards: Vec<Villager> = seen
        .iter()
        .filter(|s| s.guard && !s.baby && s.alive)
        .map(|s| s.villager)
        .collect();
    let villages = rules::group_villages(regular, guards, &|id| {
        seen.iter().find(|s| s.villager.id == id).and_then(|s| s.remembered)
    });

    for village in &villages {
        for s in seen.iter().filter(|s| village.guards.iter().any(|g| g.id == s.villager.id)) {
            remember_village(host, s.entity, village.key);
        }
    }

    for village in &villages {
        for n in 0..village.missing() {
            let pos = rules::spawn_point(village, n);
            let Some(e) = level.spawn_mob(host, "minecraft:villager", pos, SpawnReason::Event) else {
                continue;
            };
            let _ = e.add_tag(host, rules::GUARD_TAG);
            remember_village(host, e, village.key);
            let id = e.id();
            let Some(living): Option<LivingRef> = host.living(e) else { continue };
            let mut s = Seen {
                villager: Villager { id, key: Some(village.key), pos },
                entity: e, guard: true, baby: false, alive: true, remembered: Some(village.key),
            };
            let _ = &mut s;
            let _ = living;
            arm(host, items, &s);
        }
    }
}

#[derive(Default)]
pub struct GuardMod;

#[mod_api::horizon_mod]
impl Hooks for GuardMod {
    fn register(&self, r: &mut dyn Registrar, _cx: &RegistrationContext) {
        let _ = ITEMS.set(Items {
            sword: r.item_key(rules::SWORD),
            shield: r.item_key(rules::SHIELD),
            crossbow: r.item_key(rules::CROSSBOW),
            helmet: r.item_key(rules::HELMET),
            chestplate: r.item_key(rules::CHESTPLATE),
            leggings: r.item_key(rules::LEGGINGS),
            boots: r.item_key(rules::BOOTS),
        });
    }

    fn level_tick_post(&self, host: HostSide<'_>, event: &mut LevelTickPostEvent) {
        if let HostSide::Server(host) = host {
            tick(host, event.level);
        }
    }
}
