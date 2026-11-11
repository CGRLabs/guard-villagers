// Guard Villagers' row in Options > Mods.
fn on_mods(mods: &mut Vec<crate::game::native_hooks::NativeMod>) {
    use horizon_client::guard_villagers as gv;
    mods.push(crate::game::native_hooks::NativeMod {
        id: gv::ID.into(),
        title: format!("Guard Villagers {}", gv::VERSION),
        description: gv::DESCRIPTION.into(),
        keys: vec![],
    });
}