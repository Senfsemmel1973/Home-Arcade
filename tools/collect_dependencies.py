"""Collect matching bytes from USER-supplied extracted upstream trees, no downloads."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def collect(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or output.is_relative_to(ROOT) or ROOT.is_relative_to(output):
        raise RuntimeError('Use a new dependency directory outside checkout and input tree')
    lock = json.loads((ROOT / 'dependencies.json').read_text())['files']
    for name in lock:
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name or ':' in name:
            raise RuntimeError('Unsafe dependency path')
    sizes = {row['bytes'] for row in lock.values()}
    matched = {}
    for p in source.rglob('*'):
        if p.is_symlink() or not p.is_file() or p.stat().st_size not in sizes:
            continue
        raw = p.read_bytes()
        matched[hashlib.sha256(raw).hexdigest()] = raw
    missing = [n for n, row in lock.items() if row['sha256'] not in matched]
    if missing:
        raise RuntimeError('Missing exact upstream bytes; no output written: ' + ', '.join(missing))
    output.mkdir(parents=True)
    for name, row in lock.items():
        p = output / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(matched[row['sha256']])
    print('DEPENDENCIES_VERIFIED:', len(lock))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    collect(args.input, args.output)
