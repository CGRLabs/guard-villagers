#!/usr/bin/env python3
"""Package the mod as a source-only `.hnmod`, the file Horizon's registry and launcher take.

The archive holds `horizon-native.json` and `mixins/<id>/` (only `.rs` and `.toml`), with fixed dates and
modes, so the same sources always give the same bytes and the same SHA-256. Horizon's
`horizon_mods::index::native` reads it without running anything; the launcher compiles it on the pinned
Horizon revision. Based on levzzz5154's packager for Veinminer.

`hooks` in compatibility.json is what makes the bundle survive a Nightly: the launcher then builds it on any
Horizon whose `NATIVE_HOOKS_API` is at least that, instead of only the pinned commit. `--check-hooks` asks
GitHub what the pinned commit's API really is, so the number named cannot be a guess.
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOOKS_URL = ('https://raw.githubusercontent.com/{repo}/{rev}'
             '/crates/horizon-client/src/game/native_hooks.rs')
HOOKS_LINE = re.compile(r'^pub\(crate\) const NATIVE_HOOKS_API: u32 = (\d+);$', re.M)


def pinned_api(compat):
    url = HOOKS_URL.format(repo=compat['horizon_repository'].removeprefix('https://github.com/'),
                           rev=compat['horizon_revision'])
    found = HOOKS_LINE.search(urllib.request.urlopen(url, timeout=30).read().decode())
    if not found:
        raise SystemExit(f'{url} has no NATIVE_HOOKS_API line: is the commit right?')
    return int(found.group(1))


def package(compat):
    manifests = sorted((ROOT / 'mixins').glob('*/horizon-mixin.toml'))
    if len(manifests) != 1:
        raise SystemExit('a .hnmod holds one bundle: keep one mixins/<id>/horizon-mixin.toml')
    bundle = manifests[0].parent
    mixin = tomllib.loads(manifests[0].read_text())
    mod = mixin['mod']
    if bundle.name != mod['id']:
        raise SystemExit(f"rename mixins/{bundle.name}/ to mixins/{mod['id']}/ (the registry finds it by id)")
    if not mod['id'].replace('_', '').isalnum() or not mod['id'].islower():
        raise SystemExit('the registry takes ids of lowercase letters, digits and _ only')
    if mixin.get('compatibility', {}).get('horizon_revision') != compat['horizon_revision']:
        raise SystemExit('horizon-mixin.toml and compatibility.json pin different Horizon revisions')
    # The row in Options > Mods prints runtime.rs's VERSION, the archive is named by the toml's: one number.
    if f'"{mod["version"]}"' not in (bundle / 'runtime.rs').read_text():
        raise SystemExit(f'runtime.rs has no VERSION "{mod["version"]}": the row would show another version')
    if 'DESCRIPTION' not in (bundle / 'list_helper.rs').read_text():
        raise SystemExit('list_helper.rs should take its text from runtime.rs, not repeat it')
    manifest = dict(schema=1, id=mod['id'], version=mod['version'], game=compat['game'],
                    horizon=compat['horizon_revision'], mixins=compat['horizon_mixins_revision'])
    if 'hooks' in compat:
        manifest['hooks'] = compat['hooks']
    files = {'horizon-native.json': (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()}
    for path in sorted(bundle.iterdir()):
        if path.is_file() and path.suffix in ('.rs', '.toml'):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    out = ROOT / 'target' / f"{mod['id']}-{mod['version']}.hnmod"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    print(json.dumps(dict(file=str(out), size=out.stat().st_size, horizon=compat['horizon_revision'],
                          hooks=compat.get('hooks'),
                          sha256=hashlib.sha256(out.read_bytes()).hexdigest()), indent=2))


if __name__ == '__main__':
    compat = json.loads((ROOT / 'compatibility.json').read_text())
    if 'game' not in compat:
        raise SystemExit('compatibility.json needs "game": the launcher reads it from the .hnmod')
    if 'hooks' in compat and (not isinstance(compat['hooks'], int) or compat['hooks'] < 1):
        raise SystemExit('compatibility.json "hooks" is the NATIVE_HOOKS_API level the bundle needs, an integer')
    if '--check-hooks' in sys.argv:
        if 'hooks' not in compat:
            raise SystemExit('this bundle is revision-pinned, not hook-API compatible; omit --check-hooks')
        api = pinned_api(compat)
        if api < compat['hooks']:
            raise SystemExit(f"the pinned commit has hook points v{api}, the mod needs v{compat['hooks']}")
        print(json.dumps({'pinned_hooks_api': api, 'needs': compat['hooks'], 'ok': True}))
    package(compat)
