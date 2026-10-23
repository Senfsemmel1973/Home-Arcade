"""Assemble a LOCAL instance tree, never download dependencies or create a release."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def build(dependencies, output, profiles=None):
    dependencies, output = dependencies.resolve(), output.resolve()
    if output.exists() or output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(ROOT):
        raise RuntimeError('Output must be a new directory outside the source checkout')
    lock = json.loads((ROOT / 'dependencies.json').read_text())
    # Verify all dependency bytes before writing an assembled tree.
    external = {}
    for name, row in lock['files'].items():
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name or ':' in name:
            raise RuntimeError('Unsafe dependency path')
        p = dependencies / name
        if p.is_symlink() or not p.is_file():
            raise RuntimeError('Missing dependency: ' + name)
        raw = p.read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise RuntimeError('Dependency hash mismatch: ' + name)
        external[name] = raw
    own = json.loads((ROOT / 'SOURCE-MANIFEST.json').read_text())['files']
    content = {}
    for name, row in own.items():
        raw = (ROOT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise RuntimeError('Source differs from export manifest: ' + name)
        if name.startswith(('app/', 'schema/', 'web/')) or name == 'empty-catalog.json':
            content[name] = raw
        elif name.startswith('installer/'):
            content[name.removeprefix('installer/')] = raw
    content.update(external)
    if profiles is not None:
        raw = profiles.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise RuntimeError('Profile input too large')
        value = json.loads(raw)
        if not isinstance(value, dict) or not all(isinstance(k, str) and k.startswith('sha1:') and isinstance(v, dict) and {'mapper', 'bytes', 'crc32', 'region', 'evidence'} == set(v) for k, v in value.items()):
            raise RuntimeError('Expected generated MAME metadata, not games or settings')
        content['app/atari-profiles.json'] = (json.dumps(value, indent=2) + '\n').encode()
    manifest = {'product': 'Home Arcade', 'version': '2.0.0', 'catalogSchema': 1,
                'status': 'local-source-build-not-public-release', 'files': {
                    n: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in sorted(content.items())}}
    content['package-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    content['SHA256SUMS'] = ''.join(hashlib.sha256(b).hexdigest() + '  ' + n + '\n' for n, b in sorted(content.items())).encode()
    output.mkdir(parents=True)
    for name, raw in content.items():
        p = output / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        p.chmod(0o755 if name == 'runtime/bin/node' else 0o644)
    print(json.dumps({'result': 'LOCAL_BUILD_PASS', 'files': len(content), 'output': str(output)}, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--atari-profiles', type=Path, help='Optional separately generated MAME reference metadata')
    args = parser.parse_args()
    build(args.dependencies, args.output, args.atari_profiles)
