fn guard_combat(m: &crate::mobs::Mob, w: &crate::mobs::MobWorld<'_>) -> core::ops::ControlFlow<()> {
    use crate::guard_villagers as gv;
    let guard = gv::is_known_guard(m.id) || gv::is_guard(m);
    if guard
        && m.ai
            .target
            .and_then(|target| w.target_info(target))
            .is_some_and(|target| target.alive && !(target.is_player && target.creative))
    {
        // Goal navigation runs before the villager brain; panic would overwrite it.
        return core::ops::ControlFlow::Break(());
    }
    core::ops::ControlFlow::Continue(())
}
