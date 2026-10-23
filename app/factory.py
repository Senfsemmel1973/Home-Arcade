"""Deployment entry factory; only explicit root-provisioned Linux settings.

Importing this module performs no writes. There is intentionally no installer.
"""
import json
import os
from pathlib import Path
import stat

from service import Catalog, Importer, Paths, Schema
from storage import demand, read, safe_parents
from webapp import App


def root_file(path):
    path = safe_parents(path)
    s = path.lstat()
    demand(stat.S_ISREG(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022 and s.st_nlink == 1,
           'Root-eigene unveränderliche Programm-/Konfigurationsdatei erforderlich.')
    return path


def create(config='/etc/home-arcade-browser-import.json'):
    demand(os.name == 'posix' and os.geteuid() != 0, 'Nur unprivilegierter Linux-Anwendungsprozess.')
    cfg = json.loads(read(root_file(config)))
    required = {'origin', 'manifest', 'state', 'vcs', 'c64', 'covers', 'node', 'profiles', 'secret', 'networks'}
    demand(set(cfg) in (required, required | {'coverOrigin'}),
           'Unerwartete Konfiguration.')
    here = Path(__file__).resolve().parent
    for source in (here/'factory.py', here/'service.py', here/'storage.py', here/'formats.py',
                   here/'webapp.py', here/'validate.cjs', here.parent/'schema/manifest.js'):
        root_file(source)
    root_file(cfg['node'])
    p = Paths(*(Path(cfg[k]) for k in ('manifest', 'state', 'vcs', 'c64', 'covers')))
    demand(all(x.is_absolute() for x in (p.manifest, p.state, p.vcs, p.c64, p.covers)), 'Nur absolute lokale Pfade.')
    # The active catalog may stay in place only if its parent is a dedicated
    # data directory. Never grant the app write access to the protected webroot.
    demand(not p.manifest.parent.is_relative_to(here.parent), 'Programmverzeichnis darf nicht beschreibbar werden.')
    for d in (p.manifest.parent, p.state, p.vcs, p.c64, p.covers):
        s = safe_parents(d).stat()
        demand(s.st_uid == os.geteuid() and not s.st_mode & 0o077, 'Private Anwendungsdatenverzeichnisse 0700 erforderlich.')
    profiles = json.loads(read(root_file(cfg['profiles'])))
    secret = read(root_file(cfg['secret']), 1024)
    return App(Importer(p, Schema(cfg['node'], here/'validate.cjs'), profiles,
                        Catalog(cfg.get('coverOrigin', None))), secret,
               origin=cfg['origin'], networks=cfg['networks'])
