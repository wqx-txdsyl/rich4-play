"""Offline verification of the preservation boundary; does not claim gameplay parity."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
inventory = json.loads((root / 'original-inventory.json').read_text(encoding='utf-8'))
manifest = json.loads((root / 'dist/resources.json').read_text(encoding='utf-8'))
game = root / 'original-game' if (root / 'original-game/Rich4.exe').is_file() else root.parent
for item in inventory['files']:
    data = (game / item['name']).read_bytes()
    assert len(data) == item['size'], item['name']
    assert hashlib.sha256(data).hexdigest() == item['sha256'], item['name']
archive = root / 'cache/original-game.zip'
with zipfile.ZipFile(archive) as zipped:
    assert len(zipped.infolist()) == inventory['original_file_count']
    assert zipped.testzip() is None
    for item in inventory['files']:
        assert hashlib.sha256(zipped.read(item['name'])).hexdigest() == item['sha256']
digest = hashlib.sha256()
size = 0
with archive.open('rb') as original:
    for chunk in manifest['game']['chunks']:
        data = (root / 'dist' / chunk['url']).read_bytes()
        assert len(data) == chunk['size']
        assert len(data) <= 16 * 1024 * 1024
        assert hashlib.sha256(data).hexdigest() == chunk['sha256']
        assert original.read(len(data)) == data
        digest.update(data)
        size += len(data)
    assert not original.read(1)
assert size == manifest['game']['size']
assert digest.hexdigest() == manifest['game']['sha256']
print(json.dumps({'originalFilesUnchanged': inventory['original_file_count'],
                  'allArchiveEntriesVerified': True, 'chunksVerified': len(manifest['game']['chunks']),
                  'reassemblyMatchesArchive': True, 'gameplayParity': 'NOT_VERIFIED',
                  'deployment': 'NOT_DEPLOYED'}))
