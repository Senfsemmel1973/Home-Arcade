"""Read-only Home Arcade installation and data discovery; never initializes data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import importlib.util


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe(path):
    p = Path(path)
    need(p.is_absolute() and '..' not in p.parts, 'Absolute normalized path required')
    for parent in [*reversed(p.parents), p]:
        need(not parent.is_symlink(), 'Symlink in application path: ' + str(parent))
    return p


def tree(root):
    need(root.is_dir(), 'Missing directory: ' + str(root))
    files = {}
    for p in sorted(root.rglob('*')):
        s = p.lstat()
        need(stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode), 'Unexpected link/special file: ' + str(p))
        if p.is_file():
            need(s.st_nlink == 1, 'Hard-linked application file: ' + str(p))
            files[p.relative_to(root).as_posix()] = {'sha256': digest(p), 'bytes': s.st_size}
    return files


def discover(config_path='/etc/home-arcade', expect_host=None, validate_program=True):
    host = socket.gethostname().split('.')[0]
    if expect_host:
        need(host == expect_host, 'Wrong host: ' + host)
    config = safe(config_path)
    identity = json.loads((config / 'installation.json').read_bytes())
    program, data = safe(identity['program']), safe(identity['data'])
    roots = (program, data, config)
    need(all(x.exists() for x in roots), 'Installation incomplete')
    need(all(x != y and not x.is_relative_to(y) for x in roots for y in roots if x != y), 'Overlapping application roots')
    need(len(set(roots)) == 3, 'Identical application roots')
    settings = json.loads((config / 'settings.json').read_bytes())
    required = {'origin', 'manifest', 'state', 'vcs', 'c64', 'covers', 'node', 'profiles', 'secret', 'networks'}
    need(set(settings) in (required, required | {'coverOrigin'}), 'Unknown settings fields: STOP for review')
    for name in ('manifest', 'state', 'vcs', 'c64', 'covers'):
        path = safe(settings[name])
        need(path.exists() and path.is_relative_to(data), 'Unclear persistent data path: ' + name)
    need(safe(settings['node']) == program / 'runtime/bin/node', 'Unrecognized runtime path')
    need(safe(settings['profiles']) == program / 'app/atari-profiles.json', 'Unrecognized profiles path')
    need(safe(settings['secret']).is_relative_to(config), 'External secret needs explicit backup coverage')
    program_files, data_files, config_files = tree(program), tree(data), tree(config)
    evidence = 'installed-program-inventory' if validate_program else 'unvalidated-analysis-only'
    if validate_program:
        if (config / 'program-files.json').is_file():
            proof = json.loads((config / 'program-files.json').read_bytes())
            need(proof == {k: v['sha256'] for k, v in program_files.items()}, 'Program inventory mismatch: possible local changes/data in code tree')
        else:
            spec = importlib.util.spec_from_file_location('exact_legacy', Path(__file__).resolve().parent / 'legacy.py')
            legacy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(legacy)
            need(config == Path('/etc/home-arcade'), 'Legacy configuration path not recognized')
            evidence = legacy.identify(identity, program_files, has_release=(program / 'release.json').exists())
    catalog = json.loads(Path(settings['manifest']).read_bytes())
    need(catalog.get('version') == 1 and isinstance(catalog.get('games'), list), 'Unsupported catalog schema')
    games, seen = [], set()
    for game in catalog['games']:
        need(game['id'] not in seen, 'Duplicate game ID')
        seen.add(game['id'])
        rel = Path(game['rom'])
        need(not rel.is_absolute() and '..' not in rel.parts and rel.parts[:1] == ('roms',), 'Unrecognized ROM reference')
        rom = safe(data / rel)
        need(rom.is_file() and rom.is_relative_to(data), 'Missing ROM: ' + game['id'])
        need(rom.stat().st_size == game['bytes'] and digest(rom) == game['sha256'], 'ROM checksum mismatch: ' + game['id'])
        if game.get('cover'):
            cover = safe(data / game['cover'])
            need(cover.is_relative_to(data) and cover.is_file(), 'Missing/unsafe cover: ' + game['id'])
        games.append({k: game.get(k) for k in ('id', 'title', 'system', 'format', 'mapper', 'rom', 'sha256', 'bytes')})
    return {'host': host, 'version': identity['version'], 'identity': identity, 'programEvidence': evidence,
            'program': str(program), 'data': str(data), 'configuration': str(config),
            'origin': settings['origin'], 'persistentPaths': {k: settings[k] for k in ('manifest', 'state', 'vcs', 'c64', 'covers')},
            'gameCount': len(games), 'games': games, 'romFileCount': sum(k.startswith('roms/') for k in data_files),
            'programFiles': program_files, 'dataFiles': data_files, 'configurationFiles': config_files,
            'apacheActive': subprocess.run(['systemctl', 'is-active', '--quiet', 'apache2']).returncode == 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expect-host', required=True)
    p.add_argument('--config-root', default='/etc/home-arcade')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    report = discover(args.config_root, args.expect_host)
    output = Path(args.output)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    if os.environ.get('SUDO_UID'):
        os.chown(output, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    print(json.dumps({k: report[k] for k in ('host', 'version', 'program', 'data', 'configuration', 'origin', 'persistentPaths', 'gameCount', 'romFileCount', 'apacheActive')}, indent=2))
    print('Inventory report: ' + str(output))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        raise SystemExit('STOP: ' + str(e))
