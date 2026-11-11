fn guard_body(m: &crate::mobs::Mob) -> core::ops::ControlFlow<(Cow<'static, str>, Cow<'_, str>)> {
    use crate::guard_villagers as gv;

    if gv::has_guard_model(m) {
        return core::ops::ControlFlow::Break((
            gv::MODEL_MARKER.into(),
            gv::skin_texture(m.id).into(),
        ));
    }
    core::ops::ControlFlow::Continue(())
}
