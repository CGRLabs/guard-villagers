fn pose_guard_arms(
    m: &crate::mobs::Mob,
    s: &crate::mobs::anim::State,
    p: &mut crate::mobs::anim::Poses,
    value: (),
) {
    crate::guard_villagers::pose_arms(m, s, p);
    value
}
