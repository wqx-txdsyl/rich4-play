"""Reconstruct the exact game resources and browser runtime on a cloud runner.

The runner downloads large public artifacts itself; no local Git network is used.
Original non-video game files must match the supplied SHA-256 inventory.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from recover_videos import Iso9660
import prepare

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'cache'
GAME = ROOT / 'original-game'


def checksum(path: Path, algorithm='sha256'):
    value = hashlib.new(algorithm)
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def download(url, destination, expected, algorithm='sha256', expected_size=None):
    if destination.is_file() and checksum(destination, algorithm) == expected:
        return
    temporary = destination.with_suffix('.part')
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Rich4-preservation-build/1.0'})
            with urllib.request.urlopen(request, timeout=90) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if expected_size is not None and temporary.stat().st_size != expected_size:
                raise ValueError('Downloaded file size mismatch: ' + destination.name)
            if checksum(temporary, algorithm) != expected:
                raise ValueError('Downloaded file checksum mismatch: ' + destination.name)
            temporary.replace(destination)
            return
        except (OSError, ValueError) as error:
            temporary.unlink(missing_ok=True)
            print(f'Download attempt {attempt + 1} failed: {destination.name}: {error}', flush=True)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def main():
    CACHE.mkdir(exist_ok=True)
    GAME.mkdir(exist_ok=True)
    baseline = json.loads((ROOT / 'original-inventory.json').read_text(encoding='utf-8'))
    sources = json.loads((ROOT / 'resource-sources.json').read_text(encoding='utf-8'))
    iso_path = CACHE / 'RICH4_3.iso'
    print('Downloading and verifying the complete original disc image.', flush=True)
    download(sources['iso_url'], iso_path, sources['iso_sha1_catalog'], 'sha1', sources['iso_size'])
    print('Original disc SHA-1 verified.', flush=True)
    # Small installation-specific files, including the user's original EXE and saves.
    with zipfile.ZipFile(ROOT / 'cloud-input.zip') as archive:
        for name in archive.namelist():
            if name != Path(name).name or name in ('.', '..'):
                raise ValueError('Unsafe cloud input archive')
            (GAME / name).write_bytes(archive.read(name))
    iso = Iso9660(iso_path)
    try:
        files = iso.root_files()
        for item in baseline['files']:
            key = item['name'].lower()
            if key not in files:
                candidates = [e for e in files.values() if e['size'] == item['size']]
                if len(candidates) == 1:
                    files[key] = candidates[0]
        block_checks = json.loads((ROOT / 'resource-blocks.json').read_text())
        diagnostics = []
        for item in baseline['files']:
            if not item['name'].lower().endswith(('.mkf', '.mid')):
                continue
            entry = files[item['name'].lower()]
            iso.source.seek(entry['offset'])
            raw = iso.source.read(entry['size'])
            decoded = bytearray(len(raw))
            for offset in range(256):
                table = bytes((((((value ^ 0xd5) >> 2) | ((value ^ 0xd5) << 6)) - offset) & 255) for value in range(256))
                decoded[offset::256] = raw[offset::256].translate(table)
            if hashlib.sha256(decoded).hexdigest() == item['sha256']:
                (GAME / item['name']).write_bytes(decoded)
                continue
            mismatches = [i for i, h in enumerate(block_checks['files'][item['name']]) if hashlib.sha256(decoded[i*1048576:(i+1)*1048576]).hexdigest() != h]
            samples = {offset: {'iso': raw[int(offset):int(offset)+32].hex(), 'decoded': decoded[int(offset):int(offset)+32].hex(), 'local': value} for offset, value in block_checks['samples'][item['name']].items() if decoded[int(offset):int(offset)+32].hex() != value}
            diagnostics.append({'name': item['name'], 'blocks': mismatches, 'samples': samples})
        if diagnostics:
            print('DECODE_DIAGNOSTICS=' + json.dumps(diagnostics), flush=True)
            raise ValueError('Installer decoding differences need inspection')
        print('ISO root entries: ' + json.dumps({k: e['size'] for k, e in files.items()}), flush=True)
        for item in baseline['files']:
            name = item['name']
            if name.lower().endswith('.avi'):
                continue
            destination = GAME / name
            if not destination.exists():
                entry = files.get(name.lower())
                if not entry or entry['size'] != item['size']:
                    raise ValueError('Original file missing or size differs: ' + name)
                iso.source.seek(entry['offset'])
                data = iso.source.read(entry['size'])
                if hashlib.sha256(data).hexdigest() != item['sha256'] and name.lower().endswith(('.mkf', '.mid')):
                    # Original disc installer stores these files with a byte-position transform.
                    # Reverse only that storage format; require exact local SHA-256 afterwards.
                    decoded = bytearray(len(data))
                    for offset in range(256):
                        table = bytes((((((value ^ 0xd5) >> 2) | ((value ^ 0xd5) << 6)) - offset) & 255) for value in range(256))
                        decoded[offset::256] = data[offset::256].translate(table)
                    data = decoded
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('Original resource hash differs after installer decoding: ' + name)
                destination.write_bytes(data)
            if destination.stat().st_size != item['size'] or checksum(destination) != item['sha256']:
                raise ValueError('Original file preservation check failed: ' + name)
        complete = []
        for video in sources['files']:
            entry = files[video['name'].lower()]
            if entry['size'] != video['size']:
                raise ValueError('Cutscene size differs: ' + video['name'])
            original_name = next(item['name'] for item in baseline['files'] if item['name'].lower() == video['name'].lower())
            digest = iso.extract(entry, GAME / original_name)
            complete.append({'name': original_name, 'size': entry['size'], 'sha256': digest})
        if len(complete) != 21 or len({item['sha256'] for item in complete}) != 21:
            raise ValueError('Expected 21 different original cutscenes')
    finally:
        iso.close()
    print('Preserved all non-video original files byte for byte; restored all 21 original cutscenes.', flush=True)
    runtime = CACHE / 'Boxedwine26R1Web.zip'
    download(prepare.RUNTIME_URL, runtime, prepare.RUNTIME_SHA256, expected_size=122244710)
    with zipfile.ZipFile(runtime) as release:
        print('Runtime script entries: ' + json.dumps([n for n in release.namelist() if n.endswith('boxedwine.js')]), flush=True)
    font = CACHE / 'NotoSansCJKtc-Regular.otf'
    font_url = 'https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf'
    if not font.is_file():
        with urllib.request.urlopen(font_url, timeout=90) as source:
            font.write_bytes(source.read())
    font_bytes = font.read_bytes()
    if len(font_bytes) != 16435884 or hashlib.sha1(b'blob ' + str(len(font_bytes)).encode() + b'\0' + font_bytes).hexdigest() != 'f9376bae1d421520f73a3c6c9d50b22f89548301':
        raise ValueError('Pinned official CJK font verification failed')
    subprocess.run([sys.executable, str(ROOT / 'prepare.py'), '--runtime-archive', str(runtime)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'verify.py')], check=True)
    report = {'original_non_video_files_verified': len(baseline['files']) - 21, 'cutscenes_restored': len(complete),
              'cutscenes': complete, 'runtime': 'STAGED', 'gameplay': 'NOT_VERIFIED',
              'publication': 'NOT_DEPLOYED'}
    (ROOT / 'cloud-build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
