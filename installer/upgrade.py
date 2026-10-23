"""Self-contained Home Arcade updater. Explicit host; preflight by default.

Only program files and managed deployment metadata/routes are replaced.
No empty catalog, data initialization, data restore, apt, accounts or VM actions.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('arcade_inventory', HERE / 'inventory.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
need, tree, safe = inventory.need, inventory.tree, inventory.safe
PREFIXES = ('app/', 'schema/', 'web/', 'runtime/', 'provenance/')
SUPPORTED = {'1.0.0-rc2', '1.0.0', '1.0.1', '1.0.2'}


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def atomic(path, raw, mode=None):
    old = path.stat() if path.exists() else None
    temp = path.with_name(path.name + '.update-' + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode or (stat.S_IMODE(old.st_mode) if old else 0o644))
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if old and os.name == 'posix':
        os.chown(temp, old.st_uid, old.st_gid)
    os.replace(temp, path)
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def restore_proof(path, raw):
    if raw is None:
        # Only the managed proof created by this transaction is removed.
        need(path.name == 'program-files.json' and not path.is_symlink(), 'Unsafe proof restoration')
        if path.exists():
            need(path.is_file(), 'Managed proof is not a regular file')
            path.unlink()
    else:
        atomic(path, raw)


def verify_package(root=HERE):
    spec = importlib.util.spec_from_file_location('universal_clean', root / '_clean.py')
    clean = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clean)
    manifest = clean.verify_package()
    return {'product': 'Home Arcade', 'version': '2.0.0', 'catalogSchema': 1,
            'migration': 'none-schema-1', 'files': {
                name: {**row, 'mode': 0o755 if name == 'runtime/bin/node' else 0o644}
                for name, row in manifest['files'].items() if name.startswith(PREFIXES)}}


def compatibility(before):
    need(before['version'] in {'1.0.0-rc2', '2.0.0-rc1', '2.0.0'},
         'Unsupported previous version: explicit tested adapter required')
    return {'from': before['version'], 'schema': 1, 'migration': 'none-schema-1'}


def routes(site, program, files):
    root = str(program)
    need(re.fullmatch('/[A-Za-z0-9_./-]+', root), 'Unrecognized program path spelling')
    text = site.decode('utf8')
    need(text.count('</VirtualHost>') == 1 and 'WSGIDaemonProcess home-arcade ' in text and 'AuthType Basic' in text and 'Require valid-user' in text, 'Unrecognized Apache application site')
    need('  LimitRequestBody 524288\n' in text, 'Legacy import limit needs separate reviewed compatibility adapter')
    text = text.replace(' # BEGIN HOME ARCADE STATIC ASSETS\n', '').replace(' # END HOME ARCADE STATIC ASSETS\n', '')
    pattern = re.compile(r'^ Alias "/emulator/([^"\n]+)" "([^"\n]+)"\n', re.M)
    static = []
    for match in pattern.finditer(text):
        rel, target = match.groups()
        need(target == root + '/web/' + rel, 'Unknown static alias outside code root')
        if rel != 'import/':
            static.append(match.group())
    need(static, 'Static asset section not recognized')
    names = sorted(rel[4:] for rel in files if rel.startswith('web/') and rel != 'web/index.html' and not rel.startswith('web/import/'))
    block = ' # BEGIN HOME ARCADE STATIC ASSETS\n' + ''.join(f' Alias "/emulator/{rel}" "{root}/web/{rel}"\n' for rel in names) + ' # END HOME ARCADE STATIC ASSETS\n'
    position = text.index(static[0])
    text = text[:position] + '\x00ARCADE-ALIASES\x00' + text[position:]
    for line in static:
        text = text.replace(line, '')
    return text.replace('\x00ARCADE-ALIASES\x00', block).encode()


def archive_index(roots):
    result = {}
    for name, root in roots.items():
        for p in [root, *sorted(root.rglob('*'))]:
            rel = name + ('/' + p.relative_to(root).as_posix() if p != root else '')
            s = p.lstat()
            row = {'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid, 'gid': s.st_gid}
            if p.is_symlink():
                need(p.resolve().is_relative_to(root.resolve()), 'External backup symlink: ' + str(p))
                row.update(kind='symlink', target=os.readlink(p))
            elif p.is_file():
                row.update(kind='file', bytes=s.st_size, sha256=inventory.digest(p))
            else:
                need(p.is_dir(), 'Special file cannot be backed up: ' + str(p))
                row.update(kind='directory')
            result[rel] = row
    return result


def verified_backup(destination, roots):
    destination.mkdir(mode=0o700)
    expected = archive_index(roots)
    archive = destination / 'complete.tar.gz'
    with tarfile.open(archive, 'x:gz', compresslevel=1) as out:
        for name, root in roots.items():
            out.add(root, arcname=name, recursive=True)
    os.chmod(archive, 0o600)
    with archive.open('rb') as f:
        os.fsync(f.fileno())
    seen = set()
    with tarfile.open(archive, 'r:gz') as src:
        for member in src:
            need(member.name in expected and member.name not in seen, 'Unexpected backup member')
            seen.add(member.name)
            row = expected[member.name]
            need(member.mode == row['mode'] and member.uid == row['uid'] and member.gid == row['gid'], 'Backup ownership/mode mismatch')
            if row['kind'] == 'file':
                need(member.isfile() and member.size == row['bytes'], 'Backup file mismatch')
                stream = src.extractfile(member)
                h = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
                need(h.hexdigest() == row['sha256'], 'Backup checksum mismatch')
            elif row['kind'] == 'symlink':
                need(member.issym() and member.linkname == row['target'], 'Backup symlink mismatch')
            else:
                need(member.isdir(), 'Backup directory mismatch')
        need(seen == set(expected), 'Incomplete backup')
        restored = destination / 'restore-verification'
        restored.mkdir(mode=0o700)
        src.extractall(restored, filter='data')
    # The safe extraction filter strips group/world-write bits. Restore the
    # already checked archive modes only inside this private verification copy.
    for name, row in expected.items():
        if row['kind'] != 'symlink':
            os.chmod(restored / name, row['mode'])
    actual = archive_index({k: restored / k for k in roots})
    strip_owner = lambda rows: {k: {a: b for a, b in v.items() if a not in ('uid', 'gid')} for k, v in rows.items()}
    need(strip_owner(actual) == strip_owner(expected), 'Extracted backup verification failed')
    need(archive_index(roots) == expected, 'Source changed during backup')
    atomic(destination / 'backup-index.json', encode(expected), 0o600)
    atomic(destination / 'backup-proof.json', encode({'verified': True, 'sha256': inventory.digest(archive), 'entries': len(expected), 'restoreVerified': True}), 0o600)
    return expected


def system(action):
    if action == 'configtest':
        subprocess.run(['apache2ctl', 'configtest'], check=True, capture_output=True)
    else:
        subprocess.run(['systemctl', action, 'apache2'], check=True, capture_output=True)


def health(origin, before, release):
    client = build_opener(ProxyHandler({}))
    def fetch(route):
        try:
            with client.open(origin + '/emulator/' + route, timeout=30) as response:
                need(response.status == 200, 'HTTP verification failed: ' + route)
                return response.read()
        except HTTPError as error:
            error.msg = str(error.msg) + ' [route /emulator/' + route + ']'
            raise
    need(b'Home Arcade 2.0.0' in fetch(''), 'Visible RC version missing')
    catalog = json.loads(fetch('games.json'))
    need({g['id'] for g in catalog['games']} == {g['id'] for g in before['games']}, 'HTTP library IDs changed')
    need(len(catalog['games']) == before['gameCount'], 'HTTP game count changed')
    for game in before['games']:
        need(hashlib.sha256(fetch(game['rom'])).hexdigest() == game['sha256'], 'HTTP ROM mismatch: ' + game['id'])
    for name, row in release['files'].items():
        if name.startswith('web/') and name != 'web/index.html' and not name.startswith('web/import/'):
            need(hashlib.sha256(fetch(name[4:])).hexdigest() == row['sha256'], 'HTTP static content mismatch: ' + name)
    for route in ('import/', 'import-api/session'):
        try:
            fetch(route)
        except HTTPError as e:
            need(e.code == 401, 'Administration authentication changed')
        else:
            raise RuntimeError('Administration unexpectedly public')


def current_result(before, release, verify=health):
    expected = {name: {k: row[k] for k in ('bytes', 'sha256')}
                for name, row in release['files'].items()}
    current = {name: row for name, row in before['programFiles'].items()
               if name not in ('entry.wsgi', 'release.json')}
    if before['version'] != release['version']:
        return None
    need(current == expected, 'RC1 installation inconsistent: refusing repair')
    verify(before['origin'], before, release)
    need(tree(Path(before['data'])) == before['dataFiles'], 'Data changed during no-op check')
    return {'result': 'ALREADY_CURRENT', 'version': release['version'],
            'games': before['gameCount'], 'changes': False}


def stage_program(destination, program, config, release, package=HERE):
    destination.mkdir(mode=0o755)
    for rel, row in release['files'].items():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        raw = (package / rel).read_bytes()
        need(hashlib.sha256(raw).hexdigest() == row['sha256'], 'Package changed during staging')
        atomic(target, raw, row['mode'])
    entry = 'import sys\nsys.path.insert(0, ' + repr(str(program / 'app')) + ')\nfrom factory import create\napplication=create(' + repr(str(config / 'settings.json')) + ')\n'
    atomic(destination / 'entry.wsgi', entry.encode())
    atomic(destination / 'release.json', encode({k: v for k, v in release.items() if k != 'files'}))


def apply_update(before, release, backup, package=HERE, service=system, verify=None, apache_root=Path('/etc/apache2')):
    program, data, config = (Path(before[k]) for k in ('program', 'data', 'configuration'))
    tx = backup.name
    stage = program.with_name(program.name + '.stage-' + tx)
    prior = program.with_name(program.name + '.rollback-' + tx)
    failed = program.with_name(program.name + '.failed-' + tx)
    need(not any(p.exists() for p in (stage, prior, failed, backup)), 'Transaction paths already exist')
    site = apache_root / 'sites-available/home-arcade.conf'
    site_before = site.read_bytes()
    site_after = routes(site_before, program, release['files'])
    old_identity = (config / 'installation.json').read_bytes()
    proof_path = config / 'program-files.json'
    old_proof = proof_path.read_bytes() if proof_path.exists() else None
    need(old_proof is not None or before.get('programEvidence') == 'rc2-ui-refinement-v1-exact-60', 'Missing proof without exact legacy evidence')
    stage_program(stage, program, config, release, package)
    changed = False
    try:
        service('stop')
        need(tree(data) == before['dataFiles'] and tree(program) == before['programFiles'] and tree(config) == before['configurationFiles'], 'Installation changed since preflight')
        verified_backup(backup, {'program': program, 'data': data, 'configuration': config, 'apache': apache_root})
        atomic(backup / 'before-inventory.json', encode(before), 0o600)
        transaction = {'phase': 'BACKUP_VERIFIED', 'before': before, 'target': release['version'], 'programRollback': str(prior), 'failedProgram': str(failed), 'site': str(site)}
        atomic(backup / 'transaction.json', encode(transaction), 0o600)
        os.replace(program, prior)
        changed = True
        os.replace(stage, program)
        transaction['phase'] = 'PROGRAM_SWITCHED'
        atomic(backup / 'transaction.json', encode(transaction), 0o600)
        atomic(site, site_after)
        current = json.loads(old_identity)
        current['version'] = release['version']
        atomic(config / 'installation.json', encode(current))
        atomic(config / 'program-files.json', encode({k: v['sha256'] for k, v in tree(program).items()}))
        service('configtest')
        need(tree(data) == before['dataFiles'], 'Persistent data changed during upgrade')
        service('start')
        if verify:
            verify()
        need(tree(data) == before['dataFiles'], 'Persistent data changed during verification')
        untouched = lambda rows: {k: v for k, v in rows.items() if k not in ('installation.json', 'program-files.json')}
        need(untouched(tree(config)) == untouched(before['configurationFiles']), 'User settings/credentials changed')
        after = {**before, 'version': release['version'], 'programFiles': tree(program),
                 'dataFiles': tree(data), 'configurationFiles': tree(config),
                 'identity': json.loads((config / 'installation.json').read_bytes())}
        atomic(backup / 'after-inventory.json', encode(after), 0o600)
        transaction['phase'] = 'COMPLETE'
        atomic(backup / 'transaction.json', encode(transaction), 0o600)
    except BaseException as error:
        try:
            service('stop')
            if changed:
                if program.exists():
                    os.replace(program, failed)
                os.replace(prior, program)
                atomic(site, site_before)
                atomic(config / 'installation.json', old_identity)
                restore_proof(config / 'program-files.json', old_proof)
                need(tree(program) == before['programFiles'], 'Rollback program verification failed')
            service('configtest')
            service('start')
            if backup.exists():
                atomic(backup / 'failure.json', encode({'error': str(error), 'programRolledBack': changed, 'dataRestored': False}), 0o600)
        except BaseException as rollback_error:
            raise RuntimeError('STOP: update and program rollback failed; service may be stopped. Backup: ' + str(backup) + '; ' + str(rollback_error)) from error
        raise
    result = {'result': 'PASS', 'from': before['version'], 'to': release['version'], 'gamesBefore': before['gameCount'], 'gamesAfter': before['gameCount'], 'allPersistentFilesUnchanged': True, 'settingsAndCredentialsUnchanged': True, 'backupVerifiedByExtraction': True, 'backup': str(backup), 'programRollback': str(prior), 'dataRestored': False}
    atomic(backup / 'result.json', encode(result), 0o600)
    return result


def rollback_program(backup, before, service=system):
    """Never extracts/restores user data. New games and progress survive rollback."""
    backup = safe(backup)
    tx = json.loads((backup / 'transaction.json').read_bytes())
    original = tx['before']
    program, data, config = (Path(before[k]) for k in ('program', 'data', 'configuration'))
    need(all(original[k] == before[k] for k in ('host', 'program', 'data', 'configuration')), 'Rollback installation mismatch')
    if tx['phase'] == 'ROLLED_BACK':
        need(tree(program) == original['programFiles'], 'Restored program changed')
        return {'result': 'ALREADY_ROLLED_BACK', 'dataRestored': False}
    need(tx['phase'] == 'COMPLETE' and before['version'] == tx['target'], 'Rollback phase/version needs operator review')
    prior = safe(tx['programRollback'])
    need(prior == program.with_name(program.name + '.rollback-' + backup.name), 'Unexpected rollback program path')
    need(tree(prior) == original['programFiles'], 'Previous code integrity failed')
    proof = json.loads((backup / 'backup-proof.json').read_bytes())
    need(proof['restoreVerified'] and inventory.digest(backup / 'complete.tar.gz') == proof['sha256'], 'Rollback archive verification failed')
    settings = json.loads((config / 'settings.json').read_bytes())
    validation = subprocess.run([str(prior / 'runtime/bin/node'), str(prior / 'app/validate.cjs')], input=Path(settings['manifest']).read_bytes(), capture_output=True, timeout=30)
    need(validation.returncode == 0 and validation.stdout == b'OK', 'Old schema rejects current data: no rollback')
    untouched = lambda rows: {k: v for k, v in rows.items() if k not in ('installation.json', 'program-files.json')}
    need(untouched(before['configurationFiles']) == untouched(original['configurationFiles']), 'User configuration changed: review before rollback')
    with tarfile.open(backup / 'complete.tar.gz', 'r:gz') as archive:
        old_site = archive.extractfile('apache/sites-available/home-arcade.conf').read()
        old_identity = archive.extractfile('configuration/installation.json').read()
        try:
            old_proof = archive.extractfile('configuration/program-files.json').read()
        except KeyError:
            need(original.get('programEvidence') == 'rc2-ui-refinement-v1-exact-60', 'Missing backup proof without legacy evidence')
            old_proof = None
    site = safe(tx['site'])
    new_site, new_identity, new_proof = site.read_bytes(), (config / 'installation.json').read_bytes(), (config / 'program-files.json').read_bytes()
    parked = program.with_name(program.name + '.rolled-forward-' + backup.name)
    need(not parked.exists(), 'Rollback parking path exists')
    switched = False
    try:
        service('stop')
        need(tree(data) == before['dataFiles'], 'Data changed during rollback preparation')
        os.replace(program, parked)
        switched = True
        os.replace(prior, program)
        atomic(site, old_site)
        atomic(config / 'installation.json', old_identity)
        restore_proof(config / 'program-files.json', old_proof)
        need(tree(data) == before['dataFiles'] and tree(program) == original['programFiles'], 'Rollback verification failed')
        service('configtest')
        service('start')
    except BaseException:
        service('stop')
        if switched:
            if program.exists():
                os.replace(program, prior)
            os.replace(parked, program)
            atomic(site, new_site)
            atomic(config / 'installation.json', new_identity)
            atomic(config / 'program-files.json', new_proof)
        service('configtest')
        service('start')
        raise
    need(tree(data) == before['dataFiles'], 'Data changed after rollback')
    tx['phase'] = 'ROLLED_BACK'
    atomic(backup / 'transaction.json', encode(tx), 0o600)
    result = {'result': 'ROLLED_BACK', 'version': original['version'], 'dataRestored': False, 'currentDataUnchanged': True, 'gamesPreserved': before['gameCount'], 'parkedProgram': str(parked)}
    atomic(backup / 'rollback-result.json', encode(result), 0o600)
    return result


@contextmanager
def exclusive():
    import fcntl
    fd = os.open('/run/lock/home-arcade-update.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expect-host', required=True)
    p.add_argument('--expect-games', type=int)
    p.add_argument('--config-root', default='/etc/home-arcade')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--rollback', type=Path)
    p.add_argument('--baseline-inventory', type=Path)
    args = p.parse_args()
    need(os.name == 'posix' and os.geteuid() == 0, 'Root on explicitly approved Ubuntu target required')
    need(platform.machine() in ('x86_64', 'amd64'), 'Unsupported architecture')
    release_os = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    need(release_os.get('ID', '').strip('"') == 'ubuntu' and release_os.get('VERSION_ID', '').strip('"') == '24.04', 'Ubuntu 24.04 compatibility adapter required')
    for base in (HERE, *HERE.parents):
        s = base.lstat()
        need(stat.S_ISDIR(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022, 'Package path must be root-owned and not writable by others')
    with exclusive():
        release = verify_package()
        for path in HERE.rglob('*'):
            s = path.lstat()
            need(s.st_uid == 0 and not s.st_mode & 0o022, 'Unsafe package ownership/mode')
        before = inventory.discover(args.config_root, args.expect_host)
        compatibility(before)
        if args.baseline_inventory:
            baseline = json.loads(safe(args.baseline_inventory).read_bytes())
            need(all(baseline[k] == before[k] for k in ('host', 'program', 'data', 'configuration')), 'Baseline installation mismatch')
            need(baseline['dataFiles'] == before['dataFiles'], 'Persistent data differs from explicitly supplied baseline: STOP for review')
            untouched = lambda rows: {k: v for k, v in rows.items() if k not in ('installation.json', 'program-files.json')}
            need(untouched(baseline['configurationFiles']) == untouched(before['configurationFiles']), 'User configuration differs from baseline')
        need(before['apacheActive'], 'Apache must be running before update')
        if args.expect_games is not None:
            need(before['gameCount'] == args.expect_games, 'Unexpected game count: STOP')
        for base in (Path(before['program']), Path(before['configuration'])):
            for path in [base, *base.rglob('*')]:
                s = path.lstat()
                need(s.st_uid == 0 and not s.st_mode & 0o022, 'Unsafe existing code/configuration ownership')
        if args.rollback:
            need(args.apply, 'Rollback preflight only: add --apply to switch program files')
            print(json.dumps(rollback_program(args.rollback, before), indent=2))
            return
        settings = json.loads((Path(before['configuration']) / 'settings.json').read_bytes())
        r = subprocess.run([str(HERE / 'runtime/bin/node'), str(HERE / 'app/validate.cjs')], input=Path(settings['manifest']).read_bytes(), capture_output=True, timeout=30)
        need(r.returncode == 0 and r.stdout == b'OK', 'Target schema rejects current catalog: STOP before migration')
        site = Path('/etc/apache2/sites-available/home-arcade.conf')
        safe(site)
        desired_site = routes(site.read_bytes(), Path(before['program']), release['files'])
        enabled = [x.name for x in Path('/etc/apache2/sites-enabled').iterdir()]
        need(enabled == ['home-arcade.conf'], 'Other Apache sites present: STOP before service stop')
        system('configtest')
        result = current_result(before, release)
        if result:
            print(json.dumps(result, indent=2))
            return
        total = sum(row['bytes'] for group in ('programFiles', 'dataFiles', 'configurationFiles') for row in before[group].values())
        required = total * 3 + sum(row['bytes'] for row in release['files'].values()) * 2 + 1024 ** 3
        for location in (Path('/var/backups'), Path(before['program']).parent):
            need(shutil.disk_usage(location).free > required, 'Insufficient backup/stage/verification space')
        print(json.dumps({'result': 'PREFLIGHT_PASS', 'host': before['host'], 'from': before['version'], 'to': release['version'], 'games': before['gameCount'], 'migration': 'none-schema-1', 'requiredReserveBytes': required}, indent=2), flush=True)
        if not args.apply:
            return
        backup = Path('/var/backups') / ('home-arcade-update-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        result = apply_update(before, release, backup, verify=lambda: health(before['origin'], before, release))
        print(json.dumps(result, indent=2), flush=True)
        print('STOP: manual candidate acceptance. No gate release, tag, push or PROD rollout.')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        raise SystemExit('STOP: ' + str(e))
