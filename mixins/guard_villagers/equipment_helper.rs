fn guard_equipment(m: &mut crate::mobs::Mob) {
    use crate::guard_villagers as gv;
    // A guard the mod knows: the server half found it and the client half of
    // the same world reads the same list. The client's own copy of the guard
    // is armed here, so the player sees the armour and the weapon.
    if gv::is_known_guard(m.id) || gv::is_guard(m) {
        gv::keep_armed(m);
    }
}
