"""Strict JSON, content hashes, atomic writes and cooperative process locks."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f'Nonfinite JSON number: {value}')


def parse_json(text):
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant)


def read(path):
    return parse_json(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize before creating a temporary file, so invalid values leave no debris.
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False, suffix='.tmp') as f:
            temp = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


@contextlib.contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(f'Lock exists: {path}. Inspect its PID and process before removing a stale lock.') from None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'created': time.time(), 'token': token}, f)
        yield
    finally:
        # Never remove a replacement lock owned by another process.
        try:
            if read(path).get('token') == token:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass


def event(out, phase, **fields):
    data = {'time': time.time(), 'phase': phase, **fields}
    write(out / 'status.json', data)
    with (out / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps(data, ensure_ascii=False, allow_nan=False), flush=True)


@contextlib.contextmanager
def report_errors(out):
    try:
        yield
    except KeyboardInterrupt:
        event(out, 'interrupted', resumable=True)
        raise
    except Exception as exc:
        event(out, 'failed', failed=1, error=str(exc))
        raise
