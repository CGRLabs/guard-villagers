fn on_level_tick_post(game: &mut crate::game::Game<'_>, dimension: &str) {
    // The server half: the villages, their villagers, and the guards they are
    // short of. It only runs where the world is simulated.
    crate::game::guard_villagers_server::tick(game, dimension);
}
