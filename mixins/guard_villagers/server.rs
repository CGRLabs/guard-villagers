// The server half: the villagers of a village, and the guards it is short of.
//
// This runs where the world is simulated — single player and a LAN host. A
// client's copy of a world is not the world, so a client never adds a
// villager: it only draws the ones the server gave the world.
//
// It lives in the game crate (not the library) because it needs the Game.

use horizon_client::guard_villagers as gv;
use horizon_client::mobs::goals::{HurtByTarget, MeleeAttack, NearestTarget, Prey};
use horizon_client::mobs::illager::crossbow_goal;
use horizon_client::mobs::{Damage, MobEvent, Mob, Species, Who};

/// A village: the villagers it has and the guards among them, with where each
/// of them stands.
struct Village {
    key: [i32; 3],
    /// Made of villagers standing together rather than of villagers that
    /// claimed a point, so its name is only where the first of them stood.
    own: bool,
    regular: Vec<(u32, [f64; 3])>,
    guards: Vec<u32>,
}

impl Village {
    fn new(key: [i32; 3], own: bool) -> Self {
        Self {
            key,
            own,
            regular: Vec::new(),
            guards: Vec::new(),
        }
    }

    fn add(&mut self, id: u32, pos: [f64; 3]) {
        self.regular.push((id, pos));
    }

    /// Where the village is: the middle of the ground its villagers stand on.
    fn centre(&self) -> [f64; 3] {
        let n = self.regular.len().max(1) as f64;
        let mut c = [0.0; 3];
        for (_, p) in &self.regular {
            for axis in 0..3 {
                c[axis] += p[axis] / n;
            }
        }
        c
    }

    /// Fold another village into this one: the two groups stood close enough to
    /// each other to be the same village. A claimed point names the village, so
    /// it wins over a group of villagers standing together, and between two of
    /// the same kind the lower point wins. The name must not depend on who
    /// happens to stand first in the mob list: the guards remember it, and a
    /// village that renames itself every tick cannot tell that they came back.
    fn absorb(&mut self, other: &Village) {
        if self.own && !other.own || (self.own == other.own && other.key < self.key) {
            self.key = other.key;
            self.own = other.own;
        }
        self.regular.extend(other.regular.iter().copied());
        self.guards.extend(other.guards.iter().copied());
    }

    /// How many guards it is short of.
    fn missing(&self) -> usize {
        gv::guards_for(self.regular.len()).saturating_sub(self.guards.len())
    }
}

/// Villagers who stand within a village's radius of each other are one
/// village, whatever point each of them claimed. A real village hands out many
/// points — a bed here, a job site there, one meeting point — so grouping only
/// by the point a villager claimed split it into a crowd of one-villager
/// villages, each of which asked for a guard of its own.
fn merge_neighbours(villages: &mut Vec<Village>) {
    loop {
        let mut pair = None;
        for i in 0..villages.len() {
            for j in i + 1..villages.len() {
                if distance(villages[i].centre(), villages[j].centre()) <= gv::VILLAGE_RADIUS {
                    pair = Some((i, j));
                    break;
                }
            }
            if pair.is_some() {
                break;
            }
        }
        let Some((i, j)) = pair else { return };
        let other = villages.remove(j);
        villages[i].absorb(&other);
    }
}

/// The village a guard belongs to: the one whose name it remembers, when that
/// village is still there, and else the nearest of them however far away.
fn village_for(
    guard: [f64; 3],
    remembered: Option<[i32; 3]>,
    villages: &[Village],
) -> Option<usize> {
    if let Some(key) = remembered {
        if let Some(index) = villages.iter().position(|v| v.key == key) {
            return Some(index);
        }
    }
    let mut best: Option<(usize, f64)> = None;
    for (index, village) in villages.iter().enumerate() {
        let d = distance(guard, village.centre());
        if best.map_or(true, |(_, bd)| d < bd) {
            best = Some((index, d));
        }
    }
    best.map(|(index, _)| index)
}

/// The server half's tick: find the guards, keep them armed, settle the babies
/// that grew up, count the villages and add what they are short of, and let
/// the guards strike.
pub fn tick(game: &mut crate::game::Game<'_>, dimension: &str) {
    discover_guards(game);
    arm_guards(game);
    classify_babies(game);
    manage_villages(game, dimension);
    melee_pass(game);
}

/// A villager in the mod's armour is a guard — even one from a world the mod
/// did not create, and even after a restart.
fn discover_guards(game: &mut crate::game::Game<'_>) {
    let mut guards = gv::GUARDS.lock().unwrap();
    for m in game.mobs.iter() {
        if gv::is_guard(m) {
            guards.entry(m.id).or_insert(gv::NO_VILLAGE);
        }
    }
}

/// Arm the guards: the ones just spawned get the lot, the others keep what
/// they have. A guard that lost a weapon or a piece of armour gets it back.
fn arm_guards(game: &mut crate::game::Game<'_>) {
    let mut pending = gv::PENDING_GUARDS.lock().unwrap();
    let guards: Vec<u32> = gv::GUARDS.lock().unwrap().keys().copied().collect();
    for id in guards {
        let Some(m) = game.mobs.iter_mut().find(|m| m.id == id) else {
            continue;
        };
        if pending.remove(&id) {
            equip_guard(m);
        } else {
            gv::keep_armed(m);
        }
    }
}

/// A baby born next to a guard grows up into one; every other baby grows up
/// into an ordinary villager.
fn classify_babies(game: &mut crate::game::Game<'_>) {
    let mut babies = gv::BABIES.lock().unwrap();
    for m in game.mobs.iter() {
        if m.kind.species != Species::Villager || !m.is_baby() {
            continue;
        }
        if babies.contains_key(&m.id) {
            continue;
        }
        let from_guard = game
            .mobs
            .iter()
            .any(|g| gv::is_guard(g) && g.position.distance(m.position) <= gv::BREED_RADIUS);
        babies.insert(m.id, from_guard);
    }
    for m in game.mobs.iter_mut() {
        if m.kind.species != Species::Villager || m.is_baby() {
            continue;
        }
        let Some(&from_guard) = babies.get(&m.id) else {
            continue;
        };
        if from_guard {
            equip_guard(m);
            gv::GUARDS.lock().unwrap().entry(m.id).or_insert(gv::NO_VILLAGE);
        }
        babies.remove(&m.id);
    }
}

/// Give a guard the armour, the weapons and the will to fight.
pub fn equip_guard(m: &mut Mob) {
    gv::keep_armed(m);
    // Armour supplies protection without changing the villager's appearance.
    m.attrs.attack_damage = gv::SWING_DAMAGE;
    // A guard does not wander off and does not despawn.
    m.persistent = true;
    if gv::is_archer(m.id) {
        m.ai.goals.add(1, crossbow_goal(1.0, 15.0));
    } else {
        m.ai.goals.add(1, MeleeAttack::new(1.0, true));
    }
    m.ai.targets.add(1, HurtByTarget::new());
    m.ai.targets
        .add(2, NearestTarget::new(Prey::Filter(gv::prey), false).interval(5));
}

/// Count the villagers of every village and add the guards it is short of.
fn manage_villages(game: &mut crate::game::Game<'_>, dimension: &str) {
    let mut regular: Vec<(u32, Option<[i32; 3]>, [f64; 3])> = Vec::new();
    let mut guards: Vec<(u32, [f64; 3])> = Vec::new();
    for m in game.mobs.iter() {
        if m.kind.species != Species::Villager || m.removed || m.health <= 0.0 || m.is_baby() {
            continue;
        }
        let pos = [m.position.x, m.position.y, m.position.z];
        if gv::GUARDS.lock().unwrap().contains_key(&m.id) {
            guards.push((m.id, pos));
        } else {
            regular.push((m.id, gv::village_key(m), pos));
        }
    }
    if regular.is_empty() {
        return;
    }

    // The villagers that claimed a home, a bed or a meeting point start a
    // village each of their own; villagers that claimed none are in no village
    // yet and join the nearest one, or stand together in one of their own.
    // Villages whose people stand within a village's radius of each other are
    // then folded into one, so the crowd a world generated counts once.
    let mut villages: Vec<Village> = Vec::new();
    let mut homeless: Vec<(u32, [f64; 3])> = Vec::new();
    for (id, key, pos) in regular {
        match key {
            Some(key) => match villages.iter_mut().find(|v| v.key == key) {
                Some(v) => v.add(id, pos),
                None => {
                    let mut v = Village::new(key, false);
                    v.add(id, pos);
                    villages.push(v);
                }
            },
            None => homeless.push((id, pos)),
        }
    }
    for (id, pos) in homeless {
        let nearest = |villages: &[Village], only_own: bool| -> Option<usize> {
            let mut best: Option<(usize, f64)> = None;
            for (index, village) in villages.iter().enumerate() {
                if only_own && !village.own {
                    continue;
                }
                let d = distance(pos, village.centre());
                if d > gv::VILLAGE_RADIUS {
                    continue;
                }
                if best.map_or(true, |(_, bd)| d < bd) {
                    best = Some((index, d));
                }
            }
            best.map(|(index, _)| index)
        };
        match nearest(&villages, false).or_else(|| nearest(&villages, true)) {
            Some(index) => villages[index].add(id, pos),
            None => {
                // A village of its own: the villagers standing together, named
                // for the ground the first of them stood on.
                let mut v = Village::new(block_of(pos), true);
                v.add(id, pos);
                villages.push(v);
            }
        }
    }
    merge_neighbours(&mut villages);

    // Every guard belongs somewhere: one counted nowhere is a guard the village
    // replaces, and villagers walk to their beds, so the village grows without
    // end — 23 guards for 13 villagers when that was measured.
    {
        let mut known = gv::GUARDS.lock().unwrap();
        for (gid, gpos) in &guards {
            if let Some(index) = village_for(*gpos, known.get(gid).copied(), &villages) {
                villages[index].guards.push(*gid);
                known.insert(*gid, villages[index].key);
            }
        }
    }

    let options = crate::game::native_mobs::NativeSpawn::default();
    for village in &villages {
        for n in 0..village.missing() {
            let pos = spawn_point(village, n);
            let Some(id) = game.native_spawn_mob(dimension, "minecraft:villager", pos, &options)
            else {
                continue;
            };
            gv::PENDING_GUARDS.lock().unwrap().insert(id);
            gv::GUARDS.lock().unwrap().insert(id, village.key);
        }
    }
}

/// The block a villager stands on, which is the name of the village it starts
/// when it has claimed no point of a village to belong to.
fn block_of(pos: [f64; 3]) -> [i32; 3] {
    [pos[0].floor() as i32, pos[1].floor() as i32, pos[2].floor() as i32]
}

/// Where the next guard of a village stands: beside the villagers.
fn spawn_point(village: &Village, n: usize) -> [f64; 3] {
    let angle = n as f64 * std::f64::consts::TAU / 6.0;
    let centre = village.centre();
    [
        centre[0] + angle.cos() * 2.0,
        centre[1] + 1.0,
        centre[2] + angle.sin() * 2.0,
    ]
}

fn distance(a: [f64; 3], b: [f64; 3]) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// The guards strike what is next to them. Crossbow guards deal their damage
/// through their projectiles, never here.
fn melee_pass(game: &mut crate::game::Game<'_>) {
    let mut strikes: Vec<(u32, u32)> = Vec::new();
    for v in game.mobs.iter() {
        if !gv::GUARDS.lock().unwrap().contains_key(&v.id) {
            continue;
        }
        if v.removed || v.health <= 0.0 {
            continue;
        }
        if gv::is_archer(v.id) {
            continue;
        }
        if !gv::swing_ready(v.id, v.age) {
            continue;
        }
        let mut best: Option<(u32, f64)> = None;
        for t in game.mobs.iter() {
            if t.id == v.id || t.removed || t.health <= 0.0 {
                continue;
            }
            if !gv::is_threat(&t.kind.category, t.kind.species) {
                continue;
            }
            let d = v.position.distance(t.position);
            if d > gv::MELEE_REACH {
                continue;
            }
            if v.ai.target == Some(Who::Mob(t.id)) {
                best = Some((t.id, d));
                break;
            }
            if best.map_or(true, |(_, bd)| d < bd) {
                best = Some((t.id, d));
            }
        }
        if let Some((tid, _)) = best {
            strikes.push((v.id, tid));
        }
    }

    for (vid, tid) in strikes {
        let Some(v) = game.mobs.iter_mut().find(|m| m.id == vid) else {
            continue;
        };
        let from = [v.position.x, v.position.y, v.position.z];
        v.ai.target = Some(Who::Mob(tid));
        v.swing();
        v.outbox.push(MobEvent::AttackMob {
            target: tid,
            amount: gv::SWING_DAMAGE,
            source: Damage::mob(v.id, from),
        });
        gv::mark_swing(v.id, v.age);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn one(key: [i32; 3], pos: [f64; 3]) -> Village {
        let mut v = Village::new(key, false);
        v.add(1, pos);
        v
    }

    /// A village of villagers that claimed no point: named for their ground.
    fn own(pos: [f64; 3]) -> Village {
        let mut v = Village::new(block_of(pos), true);
        v.add(1, pos);
        v
    }

    #[test]
    fn neighbours_that_claimed_different_points_are_one_village() {
        // A generated village hands its villagers different beds and job
        // sites. Standing a few blocks apart they are one village, so four of
        // them are short of three guards rather than one each.
        let mut villages = vec![
            one([100, 64, 100], [100.0, 64.0, 100.0]),
            one([104, 64, 100], [104.0, 64.0, 100.0]),
            one([108, 64, 104], [108.0, 64.0, 104.0]),
            one([112, 64, 108], [112.0, 64.0, 108.0]),
        ];
        merge_neighbours(&mut villages);
        assert_eq!(villages.len(), 1);
        assert_eq!(villages[0].regular.len(), 4);
        assert_eq!(villages[0].missing(), 3);
    }

    #[test]
    fn villages_apart_stay_apart() {
        let mut villages = vec![
            one([0, 64, 0], [0.0, 64.0, 0.0]),
            one([200, 64, 0], [200.0, 64.0, 0.0]),
        ];
        merge_neighbours(&mut villages);
        assert_eq!(villages.len(), 2);
        assert_eq!(villages[0].missing() + villages[1].missing(), 2);
    }

    #[test]
    fn a_village_keeps_its_name_whatever_order_the_mobs_come_in() {
        // The guards remember their village by name. Folding the same crowd in
        // the other order must not rename it, or every guard in it wakes up
        // belonging to nothing and the village hires another.
        let mut forward = vec![
            one([104, 64, 100], [104.0, 64.0, 100.0]),
            one([100, 64, 100], [100.0, 64.0, 100.0]),
        ];
        let mut backward = vec![
            one([100, 64, 100], [100.0, 64.0, 100.0]),
            one([104, 64, 100], [104.0, 64.0, 100.0]),
        ];
        merge_neighbours(&mut forward);
        merge_neighbours(&mut backward);
        assert_eq!(forward[0].key, [100, 64, 100]);
        assert_eq!(forward[0].key, backward[0].key);
        // Villagers standing together, with no point claimed, take the name of
        // the ground they stand on; a claimed point outranks it.
        let mut with_own = vec![
            own([104.0, 64.0, 100.0]),
            one([100, 64, 100], [100.0, 64.0, 100.0]),
        ];
        merge_neighbours(&mut with_own);
        assert_eq!(with_own[0].key, [100, 64, 100]);
        assert!(!with_own[0].own);
    }

    #[test]
    fn a_guard_that_walked_to_its_bed_still_belongs_to_its_village() {
        let villages = vec![
            one([100, 64, 100], [100.0, 64.0, 100.0]),
            one([400, 64, 100], [400.0, 64.0, 100.0]),
        ];
        // The village it remembers, however far it has gone.
        assert_eq!(
            village_for([140.0, 64.0, 100.0], Some([100, 64, 100]), &villages),
            Some(0)
        );
        // A guard nobody remembers: the nearest village, and not no village at
        // all — that is what made the first measured village double its people.
        assert_eq!(village_for([420.0, 64.0, 110.0], None, &villages), Some(1));
        assert_eq!(village_for([0.0, 64.0, 0.0], None, &villages), Some(0));
        assert_eq!(village_for([0.0, 64.0, 0.0], None, &[]), None);
    }
}
