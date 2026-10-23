"""Universal RC1 installer: preflight by default, one entry for all operations."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('universal_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(config=Path('/etc/home-arcade')):
    """Do not treat a partial configuration as an empty system."""
    if config.is_symlink():
        raise RuntimeError('Symlink configuration: STOP')
    return 'existing' if config.exists() else 'clean'


def verify_package():
    return load('_clean').verify_package()


def program_tree(root):
    return load('_clean').program_tree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-host', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--hostname')
    parser.add_argument('--network', action='append')
    parser.add_argument('--listen-address', action='append')
    parser.add_argument('--login', default='admin')
    parser.add_argument('--install-dependencies', action='store_true')
    parser.add_argument('--disable-covers', action='store_true')
    parser.add_argument('--expect-games', type=int)
    parser.add_argument('--baseline-inventory', type=Path)
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Root on explicitly approved Ubuntu target required')
    clean = load('_clean')
    clean.verify_package()
    argv = ['--expect-host', args.expect_host]
    if args.apply:
        argv.append('--apply')
    if classify() == 'existing':
        if args.install_dependencies or args.disable_covers or args.network or args.listen_address or args.hostname:
            raise RuntimeError('Existing installation: omit clean-only options; configuration is preserved')
        for name in ('expect_games', 'baseline_inventory', 'rollback'):
            value = getattr(args, name)
            if value is not None:
                argv += ['--' + name.replace('_', '-'), str(value)]
        target = load('upgrade')
    else:
        if args.rollback or args.baseline_inventory or args.expect_games is not None:
            raise RuntimeError('Upgrade options require an existing installation')
        if not (args.hostname and args.network and args.listen_address):
            raise RuntimeError('Clean install requires --hostname, --network and --listen-address')
        argv += ['--hostname', args.hostname, '--login', args.login]
        for name in ('network', 'listen_address'):
            for value in getattr(args, name):
                argv += ['--' + name.replace('_', '-'), value]
        for name in ('install_dependencies', 'disable_covers'):
            if getattr(args, name):
                argv.append('--' + name.replace('_', '-'))
        target = clean
    sys.argv = [str(HERE / 'install.py'), *argv]
    if target is clean:
        with load('upgrade').exclusive():
            try:
                target.main()
            except Exception as error:
                if clean.INSTALL_STARTED and clean.BACKUP.is_dir():
                    import json
                    failure = clean.BACKUP / 'failure.json'
                    if not failure.exists():
                        clean.put(failure, (json.dumps({'result': 'STOP', 'error': str(error),
                                  'dataRestored': False, 'automaticUninstall': False,
                                  'operatorInspectionRequired': True}) + '\n').encode(), 0o600)
                raise
    else:
        target.main()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('STOP: ' + str(error))
