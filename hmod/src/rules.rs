//! Pure, host-free rules for Guard Villagers.
//!
//! Everything here is plain data so it can be tested without a game host. The
//! host-facing code in `server.rs` gathers the world into snapshots, calls these
//! rules, then writes the answers back through the mod API.

/// Two guards for every three villagers a village has: four per six, six per
/// eight. Guards are added on top, never taken from the village.
pub const GUARDS_PER_NUM: usize = 2;
pub const GUARDS_PER_DEN: usize = 3;

/// How far a guard may be from the villagers of its village, in blocks.
pub const VILLAGE_RADIUS: f64 = 32.0;
/// A baby born this close to a guard becomes a guard when it grows up.
pub const BREED_RADIUS: f64 = 5.0;
/// How close a sword guard must be to strike.
#[allow(dead_code)]
pub const MELEE_REACH: f64 = 2.5;
/// Damage of one sword swing.
#[allow(dead_code)]
pub const SWING_DAMAGE: f32 = 3.0;

/// A guard outruns the farmers it stands between (a villager's base is 0.5).
pub const GUARD_SPEED: f64 = 0.62;
/// Speed multiplier while the attack goals path toward a target.
pub const CHASE_SPEED: f64 = 1.5;
/// How close an archer comes before loosing a bolt.
#[allow(dead_code)]
pub const BOW_RANGE: f64 = 6.0;

pub const SWORD: &str = "minecraft:iron_sword";
pub const SHIELD: &str = "minecraft:shield";
pub const CROSSBOW: &str = "minecraft:crossbow";
pub const HELMET: &str = "minecraft:iron_helmet";
pub const CHESTPLATE: &str = "minecraft:iron_chestplate";
pub const LEGGINGS: &str = "minecraft:iron_leggings";
pub const BOOTS: &str = "minecraft:iron_boots";
#[allow(dead_code)]
pub const SHIELD_TAG: &str = "guard_villagers:shield";
#[allow(dead_code)]
pub const ARCHER_TAG: &str = "guard_villagers:archer";
pub const GUARD_TAG: &str = "guard_villagers:guard";

/// Guards a village of `regular` villagers gets: `ceil(2n/3)`.
pub fn guards_for(regular: usize) -> usize {
    (regular * GUARDS_PER_NUM).div_ceil(GUARDS_PER_DEN)
}

/// The role a guard id plays: one in three is an archer, one in three of the
/// rest carries a shield, the rest carry only a sword.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role {
    Archer,
    Shield,
    Sword,
}

pub fn role_of(id: u32) -> Role {
    if id % 3 == 0 {
        Role::Archer
    } else if id % 3 == 1 {
        Role::Shield
    } else {
        Role::Sword
    }
}

/// The item ids a guard wears and holds for its role.
pub fn loadout(id: u32) -> ([&'static str; 4], &'static str, Option<&'static str>) {
    let armor = [HELMET, CHESTPLATE, LEGGINGS, BOOTS];
    match role_of(id) {
        Role::Archer => (armor, CROSSBOW, None),
        Role::Shield => (armor, SWORD, Some(SHIELD)),
        Role::Sword => (armor, SWORD, None),
    }
}

pub fn distance(a: [f64; 3], b: [f64; 3]) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// The block a villager stands on, used as a stable village name when it has
/// claimed no bed, home or meeting point.
pub fn block_of(pos: [f64; 3]) -> [i32; 3] {
    [pos[0].floor() as i32, pos[1].floor() as i32, pos[2].floor() as i32]
}

/// One villager, as the grouping rules see it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Villager {
    pub id: u32,
    /// The point it claimed (bed / home / meeting), when known.
    pub key: Option<[i32; 3]>,
    pub pos: [f64; 3],
}

/// A village: its regular people and the guards among them.
#[derive(Clone, Debug)]
pub struct Village {
    pub key: [i32; 3],
    pub own: bool,
    pub regular: Vec<Villager>,
    pub guards: Vec<Villager>,
}

impl Village {
    pub fn new(key: [i32; 3], own: bool) -> Self {
        Self { key, own, regular: Vec::new(), guards: Vec::new() }
    }

    pub fn add(&mut self, v: Villager) {
        self.regular.push(v);
    }

    /// The middle of the ground its regular villagers stand on.
    pub fn centre(&self) -> [f64; 3] {
        let n = self.regular.len().max(1) as f64;
        let mut c = [0.0; 3];
        for v in &self.regular {
            for axis in 0..3 {
                c[axis] += v.pos[axis] / n;
            }
        }
        c
    }

    /// Fold another village in. A claimed point names it and wins over a group
    /// of villagers merely standing together; between two of the same kind the
    /// lower point wins, so the name never depends on mob iteration order.
    pub fn absorb(&mut self, other: &Village) {
        if (self.own && !other.own) || (self.own == other.own && other.key < self.key) {
            self.key = other.key;
            self.own = other.own;
        }
        self.regular.extend(other.regular.iter().copied());
        self.guards.extend(other.guards.iter().copied());
    }

    pub fn missing(&self) -> usize {
        guards_for(self.regular.len()).saturating_sub(self.guards.len())
    }

    pub fn surplus(&self) -> usize {
        self.guards.len().saturating_sub(guards_for(self.regular.len()))
    }

    fn nearest_guard_to(&self, pos: [f64; 3]) -> Option<usize> {
        let mut best: Option<(usize, f64)> = None;
        for (i, g) in self.guards.iter().enumerate() {
            let d = distance(g.pos, pos);
            if best.is_none_or(|(_, bd)| d < bd) {
                best = Some((i, d));
            }
        }
        best.map(|(i, _)| i)
    }
}

/// Fold villages whose people stand within a village radius into one.
pub fn merge_neighbours(villages: &mut Vec<Village>) {
    loop {
        let mut pair = None;
        for i in 0..villages.len() {
            for j in i + 1..villages.len() {
                if distance(villages[i].centre(), villages[j].centre()) <= VILLAGE_RADIUS {
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

/// Move surplus guards into villages that are short, nearest pair first.
pub fn rebalance(villages: &mut [Village]) {
    loop {
        let mut best: Option<(f64, usize, usize, usize)> = None;
        for (from, a) in villages.iter().enumerate() {
            if a.surplus() == 0 {
                continue;
            }
            for (to, b) in villages.iter().enumerate() {
                if from == to || b.missing() == 0 {
                    continue;
                }
                let Some(i) = a.nearest_guard_to(b.centre()) else { continue };
                let d = distance(a.guards[i].pos, b.centre());
                if best.is_none_or(|(bd, _, _, _)| d < bd) {
                    best = Some((d, from, to, i));
                }
            }
        }
        let Some((_, from, to, i)) = best else { return };
        let guard = villages[from].guards.remove(i);
        villages[to].guards.push(guard);
    }
}

/// The village a guard belongs to: the one whose name it remembers, else the
/// nearest however far. A guard is never allowed to belong to nothing.
pub fn village_for(pos: [f64; 3], remembered: Option<[i32; 3]>, villages: &[Village]) -> Option<usize> {
    if let Some(key) = remembered {
        if let Some(i) = villages.iter().position(|v| v.key == key) {
            return Some(i);
        }
    }
    let mut best: Option<(usize, f64)> = None;
    for (i, village) in villages.iter().enumerate() {
        let d = distance(pos, village.centre());
        if best.is_none_or(|(_, bd)| d < bd) {
            best = Some((i, d));
        }
    }
    best.map(|(i, _)| i)
}

/// Build the village list from a flat list of adult villagers and guards.
pub fn group_villages(
    regular: Vec<Villager>,
    guards: Vec<Villager>,
    remembered: &dyn Fn(u32) -> Option<[i32; 3]>,
) -> Vec<Village> {
    let mut villages: Vec<Village> = Vec::new();
    let mut homeless: Vec<Villager> = Vec::new();
    for v in regular {
        match v.key {
            Some(key) => {
                if let Some(village) = villages.iter_mut().find(|x| x.key == key) {
                    village.add(v);
                } else {
                    let mut new = Village::new(key, false);
                    new.add(v);
                    villages.push(new);
                }
            }
            None => homeless.push(v),
        }
    }
    let nearest = |pos: [f64; 3], list: &[Village], only_own: bool| -> Option<usize> {
        let mut best: Option<(usize, f64)> = None;
        for (i, village) in list.iter().enumerate() {
            if only_own && !village.own {
                continue;
            }
            let d = distance(pos, village.centre());
            if d <= VILLAGE_RADIUS && best.is_none_or(|(_, bd)| d < bd) {
                best = Some((i, d));
            }
        }
        best.map(|(i, _)| i)
    };
    for v in homeless {
        if let Some(i) = nearest(v.pos, &villages, false).or_else(|| nearest(v.pos, &villages, true)) {
            villages[i].add(v);
        } else {
            let mut new = Village::new(block_of(v.pos), true);
            new.add(v);
            villages.push(new);
        }
    }
    merge_neighbours(&mut villages);

    for g in guards {
        if let Some(i) = village_for(g.pos, remembered(g.id), &villages) {
            villages[i].guards.push(g);
        }
    }
    rebalance(&mut villages);
    villages
}

/// Where the `n`th new guard of a village stands: beside its people.
pub fn spawn_point(village: &Village, n: usize) -> [f64; 3] {
    let angle = n as f64 * std::f64::consts::TAU / 6.0;
    let c = village.centre();
    [c[0] + angle.cos() * 2.0, c[1] + 1.0, c[2] + angle.sin() * 2.0]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(id: u32, key: Option<[i32; 3]>, pos: [f64; 3]) -> Villager {
        Villager { id, key, pos }
    }

    #[test]
    fn two_guards_for_every_three_villagers() {
        assert_eq!(guards_for(0), 0);
        assert_eq!(guards_for(1), 1);
        assert_eq!(guards_for(2), 2);
        assert_eq!(guards_for(3), 2);
        assert_eq!(guards_for(4), 3);
        assert_eq!(guards_for(5), 4);
        assert_eq!(guards_for(6), 4);
        assert_eq!(guards_for(8), 6);
        assert_eq!(guards_for(12), 8);
    }

    #[test]
    fn roles_cycle_archer_shield_sword() {
        assert_eq!(role_of(3), Role::Archer);
        assert_eq!(role_of(4), Role::Shield);
        assert_eq!(role_of(5), Role::Sword);
        assert_eq!(role_of(6), Role::Archer);
    }

    #[test]
    fn neighbours_that_claimed_different_points_are_one_village() {
        let mut villages = vec![
            Village { key: [100, 64, 100], own: false, regular: vec![v(1, None, [100.0, 64.0, 100.0])], guards: vec![] },
            Village { key: [104, 64, 100], own: false, regular: vec![v(2, None, [104.0, 64.0, 100.0])], guards: vec![] },
            Village { key: [108, 64, 104], own: false, regular: vec![v(3, None, [108.0, 64.0, 104.0])], guards: vec![] },
            Village { key: [112, 64, 108], own: false, regular: vec![v(4, None, [112.0, 64.0, 108.0])], guards: vec![] },
        ];
        merge_neighbours(&mut villages);
        assert_eq!(villages.len(), 1);
        assert_eq!(villages[0].regular.len(), 4);
        assert_eq!(villages[0].missing(), 3);
    }

    #[test]
    fn villages_apart_stay_apart() {
        let mut villages = vec![
            Village { key: [0, 64, 0], own: false, regular: vec![v(1, None, [0.0, 64.0, 0.0])], guards: vec![] },
            Village { key: [200, 64, 0], own: false, regular: vec![v(2, None, [200.0, 64.0, 0.0])], guards: vec![] },
        ];
        merge_neighbours(&mut villages);
        assert_eq!(villages.len(), 2);
    }

    #[test]
    fn village_name_independent_of_mob_order() {
        let a = [104i32, 64, 100];
        let b = [100i32, 64, 100];
        let mk = |order: &[[i32; 3]]| {
            let mut vs: Vec<Village> = order.iter().map(|k| Village::new(*k, false)).collect();
            for (i, k) in order.iter().enumerate() {
                vs[i].add(v(i as u32 + 1, None, [k[0] as f64, k[1] as f64, k[2] as f64]));
            }
            merge_neighbours(&mut vs);
            vs[0].key
        };
        assert_eq!(mk(&[a, b]), mk(&[b, a]));
        assert_eq!(mk(&[a, b]), b);
    }

    #[test]
    fn surplus_guard_lends_before_hiring() {
        let mut villages = vec![
            Village {
                key: [0, 64, 0], own: false,
                regular: (1..=6).map(|i| v(i, None, [(i - 1) as f64, 64.0, 0.0])).collect(),
                guards: (1000..1008).map(|i| v(i, None, [0.0, 64.0, 0.0])).collect(),
            },
            Village {
                key: [20, 64, 0], own: false,
                regular: (20..=25).map(|i| v(i, None, [20.0 + (i - 20) as f64, 64.0, 0.0])).collect(),
                guards: vec![],
            },
        ];
        rebalance(&mut villages);
        assert_eq!(villages[0].guards.len(), 4);
        assert_eq!(villages[1].guards.len(), 4);
        assert_eq!(villages[0].missing() + villages[1].missing(), 0);
    }

    #[test]
    fn a_guard_walking_to_bed_still_belongs_to_its_village() {
        let mut villages = vec![
            Village::new([100, 64, 100], false),
            Village::new([400, 64, 100], false),
        ];
        villages[0].add(v(1, None, [100.0, 64.0, 100.0]));
        villages[1].add(v(2, None, [400.0, 64.0, 100.0]));
        assert_eq!(village_for([140.0, 64.0, 100.0], Some([100, 64, 100]), &villages), Some(0));
        assert_eq!(village_for([420.0, 64.0, 110.0], None, &villages), Some(1));
        assert_eq!(village_for([0.0, 0.0, 0.0], None, &[]), None);
    }

    #[test]
    fn grouping_creates_expected_guard_shortage() {
        let regular: Vec<Villager> = (0..8)
            .map(|i| v(i, Some([100 + i as i32, 64, 100]), [100.0 + i as f64, 64.0, 100.0]))
            .collect();
        let villages = group_villages(regular, vec![], &|_| None);
        assert_eq!(villages.len(), 1);
        assert_eq!(villages[0].missing(), 6);
    }
}
