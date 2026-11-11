fn guard_items(
    game: &crate::game::Game<'_>,
    mob: &horizon_client::mobs::Mob,
    camera: glam::DVec3,
    alpha: f64,
    light: u32,
    lit: bool,
    out: &mut Vec<horizon_client::mesher::Vertex>,
) -> core::ops::ControlFlow<()> {
    use horizon_assets::item_model::DisplayContext;
    use horizon_client::{
        items::ItemStack,
        mobs::{gear, render},
    };

    if !horizon_client::guard_villagers::has_guard_model(mob) || mob.extra.off_hand.is_none() {
        return core::ops::ControlFlow::Continue(());
    }
    for (item, off_hand) in [(&mob.extra.main_hand, false), (&mob.extra.off_hand, true)] {
        let Some(item) = item else { continue };
        let left = off_hand != mob.main_arm_left();
        let Some(transform) =
            render::held_item_transform(mob, alpha as f32, camera, game.res.mob_data(), left)
        else {
            continue;
        };
        // The pinned renderer incorrectly reuses the main-hand stack for both hands.
        let mut stack = if off_hand {
            ItemStack::new(item, 1)
        } else {
            mob.extra
                .main_hand_stack()
                .cloned()
                .unwrap_or_else(|| ItemStack::new(item, 1))
        };
        if gear::enchanted(mob, if off_hand { gear::OFF } else { gear::MAIN }) {
            stack.enchant("minecraft:unbreaking", 1);
        }
        let mut owner = crate::game::item_draw::owner_at(
            [mob.position.x, mob.position.y, mob.position.z],
            mob.body_yaw,
            &mob.kind.id,
        );
        owner.main_arm_left = mob.main_arm_left();
        if off_hand == mob.extra.using_off_hand && mob.extra.using_item > 0 {
            owner.using_this_item = true;
            owner.use_duration = 72_000;
            owner.use_item_remaining_ticks = 72_000 - mob.extra.using_item;
            owner.crossbow_charge_duration = 25;
        }
        let (context, ordinal) = if left {
            (DisplayContext::ThirdPersonLeftHand, 1)
        } else {
            (DisplayContext::ThirdPersonRightHand, 2)
        };
        let state = game.resolve_item(&stack, context, Some(&owner), mob.id as i32 + ordinal);
        if lit {
            game.submit_item_world(&state, transform, light, out);
        } else {
            game.submit_item_unlit(&state, transform, light, out);
        }
    }
    core::ops::ControlFlow::Break(())
}
