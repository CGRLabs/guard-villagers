// Guard Villagers: every village gains extra guards, on top of the villagers
// it already had.
//
// The bundle has two halves, and they do different jobs:
//
// * the **server half** runs where the world is simulated — single player and
//   a LAN host. It finds the villages, counts their villagers, and adds the
//   guards a village is short of. Only that half may add a villager: a
//   villager exists where the world that simulates it says so.
// * the **client half** only draws the guards the server gave the world: the
//   guard skin, the arms, the weapon in the hand. A client that joins
//   someone else's server sees their guards, but cannot add any.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, LazyLock, Mutex};

use crate::mobs::{Mob, MobType, Part, Species};

pub const ID: &str = "guard_villagers";
pub const VERSION: &str = "0.7.0";
pub const DESCRIPTION: &str = "Every village gains extra guards: armed villagers added on top of the farmers, smiths and traders it already had. Strike one and the others come running.";

/// Two guards for every three villagers a village has: four per six, six per
/// eight. The guards are added on top, never taken from the village.
pub const GUARDS_PER_NUM: usize = 2;
pub const GUARDS_PER_DEN: usize = 3;

/// How far a guard may be from the villagers of its village, in blocks.
pub const VILLAGE_RADIUS: f64 = 32.0;

/// A baby born this close to a guard becomes a guard when it grows up.
pub const BREED_RADIUS: f64 = 5.0;

pub const MELEE_REACH: f64 = 2.5;
pub const SWING_COOLDOWN: u32 = 20;
pub const SWING_DAMAGE: f32 = 3.0;

/// A guard's own speed, against a farmer's 0.5 (`game/mods.rs` gives the
/// villager `minecraft:movement_speed: 0.5`): a guard that walks like a
/// farmer arrives after the farmer it was meant to protect is already hurt.
pub const GUARD_SPEED: f64 = 0.62;

/// How much faster still a guard moves while it is going for what struck it.
/// The attack goals multiply the mob's speed by this while they path.
pub const CHASE_SPEED: f64 = 1.5;

/// How close an archer guard comes before it loose a bolt. The crossbow goal
/// only paths while the target is beyond this, so a wide range leaves the
/// archers standing and shooting from the far side of the village while the
/// sword guards are already on you: measured in the world, an archer at 15
/// blocks never covered a single one of the 18 between it and the player in
/// 80 ticks. At 6 it runs the same ground the sword guards run.
pub const BOW_RANGE: f64 = 6.0;
pub const SWORD: &str = "minecraft:iron_sword";
pub const SHIELD: &str = "minecraft:shield";
pub const CROSSBOW: &str = "minecraft:crossbow";
pub const HELMET: &str = "minecraft:iron_helmet";
pub const CHESTPLATE: &str = "minecraft:iron_chestplate";
pub const LEGGINGS: &str = "minecraft:iron_leggings";
pub const BOOTS: &str = "minecraft:iron_boots";
pub const MODEL_MARKER: &str = "guard_villagers#main";

/// The guards a village of `regular` villagers gets: two for every three,
/// rounded up — four per six, six per eight.
pub fn guards_for(regular: usize) -> usize {
    (regular * GUARDS_PER_NUM).div_ceil(GUARDS_PER_DEN)
}

pub fn is_archer(id: u32) -> bool {
    id % 3 == 0
}

pub fn has_shield(id: u32) -> bool {
    id % 3 == 1
}

/// What a guard holds: the weapon in its right hand and, for a third of them,
/// a shield in the left.
pub fn weapons_of(id: u32) -> (&'static str, Option<&'static str>) {
    if is_archer(id) {
        (CROSSBOW, None)
    } else if has_shield(id) {
        (SWORD, Some(SHIELD))
    } else {
        (SWORD, None)
    }
}

pub fn equip_weapons(id: u32, extra: &mut crate::mobs::Extra) {
    let (weapon, off_hand) = weapons_of(id);
    if extra.main_hand.as_deref() != Some(weapon) {
        extra.set_main_hand(Some(weapon.into()));
    }
    if extra.off_hand.as_deref() != off_hand {
        extra.off_hand = off_hand.map(Into::into);
    }
}

/// A guard wears the mod's armour. That is what marks it: the server gives
/// every guard exactly that, and the clients read it off the entity, so a
/// guard is a guard on every machine.
pub fn is_guard(m: &Mob) -> bool {
    if m.species() != Species::Villager || m.is_baby() {
        return false;
    }
    m.extra.chest.as_deref() == Some(CHESTPLATE)
}

/// The village a villager belongs to: the home, bed or meeting point it
/// claimed. A villager that claimed none of them is in no village.
pub fn village_key(m: &Mob) -> Option<[i32; 3]> {
    m.extra.home.or(m.extra.bed).or(m.extra.meeting)
}

/// The guards spawned a tick ago: they join the world after the tick that
/// made them, and are armed once they are in it.
pub static PENDING_GUARDS: LazyLock<Mutex<HashSet<u32>>> =
    LazyLock::new(|| Mutex::new(HashSet::new()));

/// The babies of the world, and whether each was born next to a guard — in
/// which case it becomes one when it grows up.
pub static BABIES: LazyLock<Mutex<HashMap<u32, bool>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// The armour and the weapons of a guard. This is what marks it: the server
/// gives every guard exactly that, and the clients read it off the entity, so
/// a guard is a guard on every machine.
///
/// Both halves call this: the server half arms the guard in the world, and
/// the client half arms its own copy of it, so the player sees the armour and
/// the weapon even where the world does not send them.
pub fn keep_armed(m: &mut Mob) {
    let mut changed = false;
    if m.extra.head.as_deref() != Some(HELMET) {
        m.extra.head = Some(HELMET.into());
        changed = true;
    }
    if m.extra.chest.as_deref() != Some(CHESTPLATE) {
        m.extra.chest = Some(CHESTPLATE.into());
        changed = true;
    }
    if m.extra.legs.as_deref() != Some(LEGGINGS) {
        m.extra.legs = Some(LEGGINGS.into());
        changed = true;
    }
    if m.extra.feet.as_deref() != Some(BOOTS) {
        m.extra.feet = Some(BOOTS.into());
        changed = true;
    }
    if m.extra.armor[0].is_none() {
        m.extra.armor[0] = Some(crate::items::ItemStack::new(HELMET, 1));
        changed = true;
    }
    if m.extra.armor[1].is_none() {
        m.extra.armor[1] = Some(crate::items::ItemStack::new(CHESTPLATE, 1));
        changed = true;
    }
    if m.extra.armor[2].is_none() {
        m.extra.armor[2] = Some(crate::items::ItemStack::new(LEGGINGS, 1));
        changed = true;
    }
    if m.extra.armor[3].is_none() {
        m.extra.armor[3] = Some(crate::items::ItemStack::new(BOOTS, 1));
        changed = true;
    }
    let (weapon, off_hand) = weapons_of(m.id);
    if m.extra.main_hand.as_deref() != Some(weapon) {
        m.extra.set_main_hand(Some(weapon.into()));
        changed = true;
    }
    if m.extra.off_hand.as_deref() != off_hand {
        m.extra.off_hand = off_hand.map(Into::into);
        changed = true;
    }
    if changed {
        // The clients learn of the equipment with the entity's next sync.
        m.needs_sync = true;
    }
}

/// Whether the mod knows this mob as one of its guards. The server half keeps
/// the list; the client half of the same world reads it.
pub fn is_known_guard(id: u32) -> bool {
    GUARDS.lock().unwrap().contains_key(&id)
}

/// The same, read from what a mob can see: guards only, so the news a hurt
/// guard passes never reaches a farmer.
pub fn is_known_guard_seen(s: &crate::mobs::Seen) -> bool {
    is_known_guard(s.id)
}

/// The villagers of a village, and the guards among them.
pub static GUARDS: LazyLock<Mutex<HashMap<u32, [i32; 3]>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
/// The village of a guard that has not been placed in one yet.
pub const NO_VILLAGE: [i32; 3] = [i32::MIN, 0, 0];

static LAST_SWING: LazyLock<Mutex<HashMap<u32, u32>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
static GUARD_MODEL: LazyLock<Mutex<Option<Arc<MobType>>>> = LazyLock::new(|| Mutex::new(None));
static PLAYER_MODEL: LazyLock<Mutex<Option<Arc<Part>>>> = LazyLock::new(|| Mutex::new(None));

pub fn load_player_model(root: &std::path::Path) {
    if PLAYER_MODEL.lock().unwrap().is_some() {
        return;
    }
    if let Some(part) = crate::mobs::load_model(root, "minecraft:player#main") {
        *PLAYER_MODEL.lock().unwrap() = Some(Arc::new(part));
    }
}

pub fn player_model() -> Option<Arc<Part>> {
    PLAYER_MODEL.lock().unwrap().clone()
}

pub fn skin_texture(id: u32) -> &'static str {
    let index = if is_archer(id) {
        3
    } else {
        ((id / 3 + id % 3 - 1) % 3) as usize
    };
    horizon_client_render::guard_skins::SKINS[index].0
}

pub fn guard_model() -> Option<Arc<MobType>> {
    GUARD_MODEL.lock().unwrap().clone()
}

pub fn set_guard_model(m: Arc<MobType>) {
    *GUARD_MODEL.lock().unwrap() = Some(m);
}

pub fn has_guard_model(m: &Mob) -> bool {
    m.species() == Species::Villager
        && !m.is_baby()
        && m.kind.layers.contains_key(MODEL_MARKER)
}

pub fn pose_arms(m: &Mob, s: &crate::mobs::anim::State, p: &mut crate::mobs::anim::Poses) {
    use crate::mobs::illager::{self, ArmPose};

    if !has_guard_model(m) {
        return;
    }
    let crossbow = m.extra.main_hand.as_deref() == Some(CROSSBOW);
    let pose = if crossbow && m.extra.using_item > 0 {
        ArmPose::CrossbowCharge
    } else if crossbow {
        ArmPose::CrossbowHold
    } else if s.swing > 0.0 {
        ArmPose::Attacking
    } else {
        ArmPose::Neutral
    };
    // Keep the villager head/leg animation; only replace the arms.
    let mut arms = p.clone();
    illager::anim_pose(m, s, &mut arms, pose);
    for name in ["right_arm", "left_arm"] {
        *p.get(name) = *arms.get(name);
    }
}

pub fn swing_ready(id: u32, age: u32) -> bool {
    LAST_SWING
        .lock()
        .unwrap()
        .get(&id)
        .is_none_or(|&last| age.wrapping_sub(last) >= SWING_COOLDOWN)
}

pub fn mark_swing(id: u32, age: u32) {
    LAST_SWING.lock().unwrap().insert(id, age);
}

pub fn is_threat(category: &str, species: Species) -> bool {
    category == "monster" && species != Species::Creeper
}

pub fn prey(s: &crate::mobs::Seen) -> bool {
    s.hostile && s.species != Species::Creeper
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_role_maps_to_a_supplied_skin() {
        let names: std::collections::HashSet<_> = (0..30).map(skin_texture).collect();
        assert_eq!(names.len(), 4);
        assert_eq!(skin_texture(3), "guard_villagers:entity/villager-archer");
        assert_eq!(skin_texture(0), "guard_villagers:entity/villager-archer");
        for id in [1, 2, 4, 5, 7, 8] {
            assert_ne!(skin_texture(id), "guard_villagers:entity/villager-archer");
        }
    }

    #[test]
    fn rearming_restores_weapons_without_unloading_a_crossbow() {
        use crate::{items::ItemStack, mobs::Extra};

        let mut extra = Extra::default();
        equip_weapons(3, &mut extra);
        let mut charged = ItemStack::new(CROSSBOW, 1);
        charged.data_mut().charged = vec![ItemStack::new("minecraft:arrow", 1)];
        extra.set_main_hand_stack(Some(charged));
        extra.using_item = 12;
        equip_weapons(3, &mut extra);
        assert_eq!(
            extra
                .main_hand_stack()
                .unwrap()
                .data()
                .unwrap()
                .charged
                .len(),
            1
        );
        assert_eq!(extra.using_item, 12);
        extra.set_main_hand(None);
        equip_weapons(3, &mut extra);
        assert_eq!(extra.main_hand.as_deref(), Some(CROSSBOW));
        equip_weapons(4, &mut extra);
        assert_eq!(extra.main_hand.as_deref(), Some(SWORD));
        assert_eq!(extra.off_hand.as_deref(), Some(SHIELD));
        equip_weapons(5, &mut extra);
        assert_eq!(extra.main_hand.as_deref(), Some(SWORD));
        assert!(extra.off_hand.is_none());
    }

    #[test]
    fn loadouts_include_crossbow_sword_shield_and_sword_only() {
        assert!(is_archer(3));
        assert!(!has_shield(3));
        assert!(!is_archer(4));
        assert!(has_shield(4));
        assert!(!is_archer(5));
        assert!(!has_shield(5));
    }

    #[test]
    fn two_guards_for_every_three_villagers() {
        // Four per six, six per eight.
        assert_eq!(guards_for(6), 4);
        assert_eq!(guards_for(8), 6);
        assert_eq!(guards_for(1), 1);
        assert_eq!(guards_for(2), 2);
        assert_eq!(guards_for(3), 2);
        assert_eq!(guards_for(4), 3);
        assert_eq!(guards_for(5), 4);
        assert_eq!(guards_for(12), 8);
        // A village of one still gets one guard.
        assert_eq!(guards_for(0), 0);
    }
}
