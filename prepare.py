"""Preserve the local Rich4 installation and stage the official browser runtime.

Python 3.11+, no third-party dependencies. Original files are never modified.
This is a compatibility-port preparation tool; gameplay/audio parity is unverified.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
GAME = HERE / 'original-game' if (HERE / 'original-game' / 'Rich4.exe').is_file() else HERE.parent
DIST = HERE / 'dist'
CACHE = HERE / 'cache'
CHUNK_SIZE = 2 * 1024 * 1024
RUNTIME_URL = 'https://github.com/danoon2/Boxedwine/releases/download/26R1.0/Boxedwine26R1Web.zip'
RUNTIME_SHA256 = 'ebc634e921f7c65980a7094f3efad84873cede8011eb7dd204446ff1de982945'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def split_file(source: Path, stem: str) -> dict:
    package_hash = sha256(source)
    directory = stem + '-' + package_hash[:16] + '-' + str(CHUNK_SIZE)
    output = DIST / 'assets' / directory
    output.mkdir(parents=True, exist_ok=True)
    chunks = []
    with source.open('rb') as stream:
        index = 0
        while block := stream.read(CHUNK_SIZE):
            filename = f'{stem}.{index:03d}.bin'
            (output / filename).write_bytes(block)
            chunks.append({'url': 'assets/' + directory + '/' + filename, 'size': len(block),
                           'sha256': hashlib.sha256(block).hexdigest()})
            index += 1
    return {'size': source.stat().st_size, 'sha256': package_hash, 'chunks': chunks}


def prepare_game() -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in GAME.iterdir() if p.is_file()), key=lambda p: p.name.lower())
    required = ['Rich4.exe', 'Data.mkf', 'map.mkf', 'Panel.mkf', 'Speaking.mkf']
    for name in required:
        if not (GAME / name).is_file():
            raise RuntimeError(f'Missing original game file: {name}')
    inventory = [{'name': p.name, 'size': p.stat().st_size, 'sha256': sha256(p)} for p in files]
    archive = CACHE / 'original-game.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as dest:
        for item in inventory:
            info = zipfile.ZipInfo(item['name'], (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            dest.writestr(info, (GAME / item['name']).read_bytes())
    with zipfile.ZipFile(archive) as preserved:
        assert len(preserved.infolist()) == len(inventory)
        for item in inventory:
            assert hashlib.sha256(preserved.read(item['name'])).hexdigest() == item['sha256'], item['name']
    avi = [item for item in inventory if item['name'].lower().endswith('.avi')]
    summary = {
        'original_file_count': len(inventory), 'original_size': sum(i['size'] for i in inventory),
        'files': inventory,
        'observations': {
            'avi_count': len(avi), 'avi_unique_hashes': len({i['sha256'] for i in avi}),
            'avi_sizes': sorted({i['size'] for i in avi}),
            'parity_status': 'NOT_VERIFIED', 'runtime_status': 'NOT_DOWNLOADED',
            'deployment_status': 'NOT_DEPLOYED',
        },
    }
    write_json(HERE / 'original-inventory.json', summary)
    manifest = {'game': split_file(archive, 'rich4'), 'runtime': None,
                'parityStatus': 'NOT_VERIFIED'}
    write_json(DIST / 'resources.json', manifest)
    return manifest


def stage_runtime(manifest: dict, supplied_archive: str | None) -> None:
    archive = Path(supplied_archive).resolve() if supplied_archive else CACHE / 'Boxedwine26R1Web.zip'
    if not archive.exists():
        print('Downloading the official Boxedwine 26R1 Web release...', flush=True)
        partial = archive.with_suffix('.partial')
        try:
            with urllib.request.urlopen(RUNTIME_URL, timeout=30) as source, partial.open('wb') as dest:
                shutil.copyfileobj(source, dest)
            if sha256(partial) != RUNTIME_SHA256:
                raise RuntimeError('Official runtime archive SHA-256 mismatch')
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    if sha256(archive) != RUNTIME_SHA256:
        raise RuntimeError('Official runtime archive SHA-256 mismatch')
    with zipfile.ZipFile(archive) as release:
        names = release.namelist()
        candidates = [n for n in names if n.lower() == 'singlethreaded/boxedwine.js']
        if len(candidates) != 1:
            raise RuntimeError('Cannot uniquely locate the single-threaded Wine 11 runtime in the official release')
        prefix = candidates[0].rsplit('/', 1)[0] + '/'
        target = DIST / 'runtime'
        target.mkdir(parents=True, exist_ok=True)
        for filename in ['boxedwine.js', 'boxedwine.wasm', 'boxedwine.zip']:
            member = 'Wine11/boxedwine.zip' if filename == 'boxedwine.zip' else prefix + filename
            if member not in names:
                raise RuntimeError(f'Official release is missing {member}')
            temp = CACHE / filename
            temp.write_bytes(release.read(member))
            if filename.endswith('.zip'):
                font = CACHE / 'NotoSansCJKtc-Regular.otf'
                if font.is_file():
                    with zipfile.ZipFile(temp, 'a', compression=zipfile.ZIP_DEFLATED) as rootfs:
                        rootfs.write(font, 'home/username/.wine/drive_c/windows/Fonts/NotoSansCJKtc-Regular.otf')
                manifest['runtime'] = split_file(temp, 'wine11')
            elif temp.stat().st_size > 24 * 1024 * 1024:
                raise RuntimeError(f'{filename} exceeds the static hosting per-file limit; split runtime loading is required')
            else:
                shutil.copy2(temp, target / filename)
        write_json(DIST / 'resources.json', manifest)
    inventory = json.loads((HERE / 'original-inventory.json').read_text(encoding='utf-8'))
    inventory['observations']['runtime_status'] = 'DOWNLOADED_NOT_TESTED'
    write_json(HERE / 'original-inventory.json', inventory)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets-only', action='store_true', help='Preserve and verify originals without downloading the runtime')
    parser.add_argument('--runtime-archive', help='Previously downloaded official Boxedwine26R1Web.zip')
    args = parser.parse_args()
    DIST.mkdir(parents=True, exist_ok=True)
    for source in (HERE / 'web').iterdir():
        if source.is_file():
            shutil.copy2(source, DIST / source.name)
    shutil.copy2(DIST / 'index.html', DIST / 'play.html')
    shutil.copy2(HERE / 'vendor' / 'boxedwine-shell.upstream.js', DIST / 'boxedwine-shell.js')
    licenses = DIST / 'licenses'
    licenses.mkdir(exist_ok=True)
    for source in (HERE / 'vendor').glob('*LICENSE*'):
        shutil.copy2(source, licenses / source.name)
    manifest = prepare_game()
    inventory = json.loads((HERE / 'original-inventory.json').read_text(encoding='utf-8'))
    print(json.dumps({'originalFiles': inventory['original_file_count'], 'archiveBytes': manifest['game']['size'],
                      'chunks': len(manifest['game']['chunks']), 'verified': True}), flush=True)
    if not args.assets_only:
        stage_runtime(manifest, args.runtime_archive)
        print('Runtime staged. Browser gameplay, Chinese text, audio, MIDI and save/load still require validation.', flush=True)


if __name__ == '__main__':
    main()
