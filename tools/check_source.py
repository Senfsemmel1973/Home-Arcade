"""Small offline export check; does not claim to prove absence of every secret."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'SOURCE-MANIFEST.json').read_text())['files']
actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts and 'lab-data' not in p.parts}
assert actual == set(manifest) | {'SOURCE-MANIFEST.json'}, sorted(actual ^ (set(manifest) | {'SOURCE-MANIFEST.json'}))
for name, row in manifest.items():
    p = ROOT / name
    assert not p.is_symlink(), name
    raw = p.read_bytes()
    assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], name
    assert b'\0' not in raw, name
    text = raw.decode('utf-8-sig')
    assert not re.search(r'-----BEGIN (?:OPENSSH|RSA|EC|DSA)? ?PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b', text), name
    assert not set(Path(name).parts) & {'roms', 'covers', 'screenshots', 'backups', 'dist', 'vendor', 'provenance'}, name
assert json.loads((ROOT / 'empty-catalog.json').read_text()) == {'version': 1, 'games': []}
assert json.loads((ROOT / 'app/atari-profiles.json').read_text()) == {}
print('SOURCE_CHECK_PASS:', len(manifest), 'UTF-8 source/documentation files; exact allowlist; no media, archives or binaries')
