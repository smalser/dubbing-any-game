"""Preflight for the required game-research toolkit; never invokes paid services."""
import importlib.metadata
import json
import subprocess
import sys


REVISION = 'c1dff21663665dd17af289744a301b66e369605e'
INSTALL = 'python -m pip install -e ".[game]"'


def inspect_toolkit():
    result = {'passed': False, 'required_revision': REVISION, 'install': INSTALL}
    try:
        distribution = importlib.metadata.distribution('universal-modder')
    except importlib.metadata.PackageNotFoundError:
        return {**result, 'detail': 'Universal Modder is required for game integration; install the game extra'}
    result['version'] = distribution.version
    try:
        provenance = json.loads(distribution.read_text('direct_url.json') or '{}')
        if not isinstance(provenance, dict) or not isinstance(provenance.get('vcs_info', {}), dict):
            raise ValueError('Malformed Universal Modder installation metadata')
        revision = provenance.get('vcs_info', {}).get('commit_id')
        result['revision'] = revision
        if revision != REVISION:
            return {**result, 'detail': 'Toolkit revision is missing or differs from the tested requirement'}
        process = subprocess.run([sys.executable, '-m', 'um', '--version'],
                                 capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=20)
        result['passed'] = process.returncode == 0
        result['detail'] = process.stdout.strip() if result['passed'] else 'python -m um --version failed'
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result['detail'] = str(exc)
    return result


def require_toolkit():
    result = inspect_toolkit()
    if not result['passed']:
        raise ValueError(result['detail'] + '; ' + INSTALL)
    return result
