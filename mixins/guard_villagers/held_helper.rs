fn guard_hand(
    m: &crate::mobs::Mob,
    alpha: f32,
    camera: glam::DVec3,
    data: &crate::mobs::MobData,
    left: bool,
) -> core::ops::ControlFlow<Option<glam::Mat4>> {
    if !crate::guard_villagers::has_guard_model(m) {
        return core::ops::ControlFlow::Continue(());
    }
    let arm = if left { "left_arm" } else { "right_arm" };
    let hand = crate::mobs::render::part_transform(m, alpha, camera, data, arm).map(|hand| {
        hand * glam::Mat4::from_rotation_x(-std::f32::consts::FRAC_PI_2)
            * glam::Mat4::from_rotation_y(std::f32::consts::PI)
            * glam::Mat4::from_translation(glam::Vec3::new(
                if left { -1.0 / 16.0 } else { 1.0 / 16.0 },
                2.0 / 16.0,
                -10.0 / 16.0,
            ))
    });
    core::ops::ControlFlow::Break(hand)
}
