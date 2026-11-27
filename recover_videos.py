"""Extract the 21 original cutscenes from a verified Rich4 Time Travel ISO.

No executable is installed or launched. The existing game folder is read-only.
Usage: python recover_videos.py --iso D:\path\RICH4_3.iso
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent
SECTOR = 2048


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


class Iso9660:
    def __init__(self, path: Path):
        self.source = path.open('rb')
        self.size = path.stat().st_size
        self.source.seek(16 * SECTOR)
        descriptor = self.source.read(SECTOR)
        if descriptor[:7] != b'\x01CD001\x01':
            self.source.close()
            raise ValueError('Not a supported ISO9660 image')
        self.root = self.record(descriptor[156:190])

    def close(self):
        self.source.close()

    def record(self, data: bytes) -> dict:
        if len(data) < 34 or data[0] < 34 or data[0] > len(data):
            raise ValueError('Invalid ISO directory record')
        extent = struct.unpack_from('<I', data, 2)[0]
        size = struct.unpack_from('<I', data, 10)[0]
        if extent != struct.unpack_from('>I', data, 6)[0] or size != struct.unpack_from('>I', data, 14)[0]:
            raise ValueError('ISO directory endian fields disagree')
        if data[25] & 0x80:
            raise ValueError('Multi-extent ISO files are not supported')
        if extent * SECTOR + size > self.size:
            raise ValueError('ISO entry is outside the image')
        count = data[32]
        if 33 + count > len(data):
            raise ValueError('Invalid ISO filename length')
        name = data[33:33 + count].decode('ascii').split(';', 1)[0].rstrip('.')
        return {'name': name, 'offset': extent * SECTOR, 'size': size, 'directory': bool(data[25] & 2)}

    def root_files(self) -> dict[str, dict]:
        if self.root['size'] > 16 * 1024 * 1024:
            raise ValueError('ISO root directory is too large')
        self.source.seek(self.root['offset'])
        data = self.source.read(self.root['size'])
        result = {}
        pos = 0
        while pos < len(data):
            length = data[pos]
            if not length:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            entry = self.record(data[pos:pos + length])
            if not entry['directory']:
                key = entry['name'].lower()
                if key in result:
                    raise ValueError('Duplicate ISO root filename')
                result[key] = entry
            pos += length
        return result

    def file_hash(self, entry: dict) -> str:
        self.source.seek(entry['offset'])
        digest = hashlib.sha256()
        remaining = entry['size']
        while remaining:
            block = self.source.read(min(remaining, 1024 * 1024))
            if not block:
                raise ValueError('Truncated ISO file')
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest()

    def extract(self, entry: dict, destination: Path) -> str:
        self.source.seek(entry['offset'])
        temporary = destination.with_suffix(destination.suffix + '.part')
        digest = hashlib.sha256()
        remaining = entry['size']
        try:
            with temporary.open('wb') as target:
                first = True
                while remaining:
                    block = self.source.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise ValueError('Truncated ISO video')
                    if first and (block[:4] != b'RIFF' or block[8:12] != b'AVI '):
                        raise ValueError('Expected AVI RIFF data: ' + entry['name'])
                    first = False
                    target.write(block)
                    digest.update(block)
                    remaining -= len(block)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    path = Path(args.iso).resolve()
    manifest = json.loads((ROOT / 'resource-sources.json').read_text(encoding='utf-8'))
    if path.stat().st_size != manifest['iso_size']:
        raise ValueError('ISO size differs from the catalog entry')
    actual_sha1 = hash_file(path, 'sha1')
    if actual_sha1 != manifest['iso_sha1_catalog']:
        raise ValueError('ISO SHA-1 differs from the catalog entry; originals will not be replaced')
    iso = Iso9660(path)
    try:
        files = iso.root_files()
        original = json.loads((ROOT / 'original-inventory.json').read_text(encoding='utf-8'))
        compared = []
        for item in original['files']:
            if not item['name'].lower().endswith(('.mkf', '.mid')):
                continue
            entry = files.get(item['name'].lower())
            if not entry or entry['size'] != item['size'] or iso.file_hash(entry) != item['sha256']:
                raise ValueError('Core resource mismatch: ' + item['name'])
            compared.append(item['name'])
        for item in manifest['files']:
            entry = files.get(item['name'].lower())
            if not entry or entry['size'] != item['size']:
                raise ValueError('Video size/name mismatch: ' + item['name'])
        if args.check_only:
            print(json.dumps({'isoSha1Verified': True, 'coreFilesCompared': len(compared),
                              'videoEntriesVerified': len(manifest['files'])}))
            return
        destination = ROOT / 'resources-complete'
        destination.mkdir(exist_ok=True)
        recovered = []
        for item in manifest['files']:
            target = destination / item['name']
            entry = files[item['name'].lower()]
            if target.exists():
                expected = iso.file_hash(entry)
                if hash_file(target, 'sha256') != expected:
                    raise ValueError('Existing staged file differs; preserve and inspect it first: ' + target.name)
                checksum = expected
            else:
                checksum = iso.extract(entry, target)
            recovered.append({**item, 'sha256': checksum, 'local_status': 'EXTRACTED_FROM_VERIFIED_ISO'})
            print('Verified ' + target.name, flush=True)
        result = {'status': 'EXTRACTED_NOT_GAMEPLAY_TESTED', 'iso_sha1': actual_sha1,
                  'core_files_compared': compared, 'files': recovered}
        (ROOT / 'recovered-video-inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('All 21 cutscenes extracted. Game originals remain unchanged; playback still needs validation.')
    finally:
        iso.close()


if __name__ == '__main__':
    main()
