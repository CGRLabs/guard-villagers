fn guard_layers(m: &crate::mobs::Mob, age: f32) -> core::ops::ControlFlow<Vec<Layer>> {
    let _ = age;
    if crate::guard_villagers::has_guard_model(m) {
        // The supplied skins already contain outfits; villager overlays use different UVs.
        return core::ops::ControlFlow::Break(Vec::new());
    }
    core::ops::ControlFlow::Continue(())
}
