"""Validate selected dialogue without guessing ownership or repairing identifiers."""
from pathlib import Path
import re

from .storage import read


STATUSES = {'ready', 'reviewed', 'unknown', 'blocked', 'excluded', 'silence', 'nonverbal', 'development'}
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
            *(f'LPT{i}' for i in range(1, 10))}


def load_manifest(args):
    path = Path(args.manifest).resolve()
    obj = read(path)
    if (not isinstance(obj, dict) or type(obj.get('schema_version')) is not int
            or obj['schema_version'] != 1 or not isinstance(obj.get('lines'), list)):
        raise ValueError('Expected integer schema_version=1 and lines array')
    requested = set(args.ids.split(',')) if args.ids else None
    if requested and any(not i or i != i.strip() for i in requested):
        raise ValueError('--ids must contain nonempty exact IDs without surrounding spaces')
    rows, ids = [], set()
    for item in obj['lines']:
        if not isinstance(item, dict):
            raise ValueError('Every manifest line must be an object')
        r = dict(item)
        ident = r.get('id', '')
        if (not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', ident)
                or ident.upper() in RESERVED or ident.casefold() in ids):
            raise ValueError(f'Unsafe, reserved or case-insensitive duplicate ID: {ident}')
        ids.add(ident.casefold())
        status = r.get('status', 'ready')
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError(f'Unknown status for {ident}: {status!r}; use an explicit excluded status and reason')
        if not isinstance(r.get('blockers', []), list):
            raise ValueError(f'blockers must be an array: {ident}')
        if 'scene' in r and not isinstance(r['scene'], str):
            raise ValueError(f'scene must be a string: {ident}')
        if status not in ('ready', 'reviewed'):
            if not isinstance(r.get('reason'), str) or not r['reason'].strip():
                raise ValueError(f'Excluded line requires a reason: {ident}')
            continue
        if r.get('blockers'):
            raise ValueError(f'Ready line has unresolved blockers: {ident}')
        if not all(isinstance(r.get(k), str) and r[k].strip() for k in ('speaker', 'text', 'reference')):
            raise ValueError(f'Missing speaker/text/reference: {ident}')
        for key in ('reference', 'original'):
            if key not in r:
                continue
            if not isinstance(r[key], str) or not r[key].strip():
                raise ValueError(f'{key} must be a nonempty path string: {ident}')
            r[key] = str((path.parent / r[key]).resolve())
        fmt = r.get('format', {})
        if not isinstance(fmt, dict) or any(type(fmt.get(k)) is not int or fmt[k] <= 0
                                            for k in ('sample_rate', 'channels', 'frames')):
            raise ValueError(f'Expected positive integer format sample_rate/channels/frames: {ident}')
        if fmt['channels'] > 8:
            raise ValueError(f'More than 8 channels is unsupported: {ident}')
        if requested and ident not in requested:
            continue
        if args.scene and r.get('scene') != args.scene:
            continue
        rows.append(r)
    if requested and requested - {r['id'] for r in rows}:
        raise ValueError('Requested IDs missing, excluded or filtered')
    if args.limit is not None:
        rows = rows[:args.limit]
    if not rows:
        raise ValueError('No eligible dialogue selected')
    for r in rows:
        for key in ('reference', 'original'):
            if key in r and not Path(r[key]).is_file():
                raise ValueError(f'Missing {key}: {r[key]}')
    return rows


def exclusions(args, rows):
    selected = {r['id'] for r in rows}
    return [{'id': r['id'], 'status': r.get('status', 'ready'),
             'reason': r.get('reason', 'outside selection')}
            for r in read(args.manifest)['lines'] if r['id'] not in selected]
