fn on_frame(game: &mut crate::game::Game<'_>, elapsed: std::time::Duration) {
    use horizon_client::guard_villagers as gv;
    use std::sync::Arc;

    let _ = elapsed;
    let Some(part) = gv::player_model() else {
        return;
    };
    for m in &mut game.mobs {
        // Only the guards wear the guard model: the villagers a village has
        // keep their own skins, their professions and their lives.
        let guard = gv::is_known_guard(m.id) || gv::is_guard(m);
        if !guard || gv::has_guard_model(m) {
            continue;
        }
        // The client's own copy of the guard wears the armour and holds the
        // weapon, so the player sees it as it is.
        gv::keep_armed(m);
        let model = gv::guard_model().unwrap_or_else(|| {
            let mut kind = (*m.kind).clone();
            kind.model = part.clone();
            kind.layers.insert("villager#main".into(), part.clone());
            kind.layers.insert(gv::MODEL_MARKER.into(), part.clone());
            let kind = Arc::new(kind);
            gv::set_guard_model(kind.clone());
            kind
        });
        m.kind = model;
    }
}
