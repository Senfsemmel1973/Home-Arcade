"""Exact historical program recognition, never creates an installed proof."""
import json
from pathlib import Path

PROFILE = 'rc2-ui-refinement-v1-exact-60'
HERE = Path(__file__).resolve().parent


def identify(identity, rows, has_release=False, reference=None):
    expected_identity = dict(version='1.0.0-rc2', program='/opt/home-arcade',
                             data='/var/lib/home-arcade', user='home-arcade')
    if identity != expected_identity or has_release:
        raise RuntimeError('Legacy identity/layout not recognized')
    reference = reference if reference is not None else json.loads((HERE / 'legacy-reference.json').read_bytes())
    actual = {name: row['sha256'] for name, row in rows.items()}
    if reference.get('profile') != PROFILE or len(reference.get('files', {})) != 60 or actual != reference['files']:
        raise RuntimeError('Legacy program differs from historical reference; no upgrade')
    return PROFILE
