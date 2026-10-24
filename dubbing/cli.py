"""Manifest-driven, resumable synthesis with explicit audio export stages."""
import argparse
import contextlib
import hashlib
import html
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile

from .platforms import diagnose


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     delete=False, suffix='.tmp') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        name = f.name
    os.replace(name, path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'Lock exists: {path}. Check its PID before removing a stale lock.')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({'pid': os.getpid(), 'created': time.time()}, f)
        yield
    finally:
        path.unlink(missing_ok=True)


def audio(path):
    import numpy as np
    import soundfile as sf
    a, sr = sf.read(path, dtype='float32', always_2d=True)
    if not len(a) or not np.isfinite(a).all():
        raise ValueError(f'Empty/nonfinite audio: {path}')
    peak = float(np.max(np.abs(a)))
    if peak <= 1e-7 or peak >= 1:
        raise ValueError(f'Silent or clipped audio: {path}')
    return a, sr


def load_manifest(args):
    path = Path(args.manifest).resolve()
    obj = read(path)
    if not isinstance(obj, dict) or obj.get('schema_version') != 1 or not isinstance(obj.get('lines'), list):
        raise ValueError('Expected schema_version=1 and lines array')
    rows, ids = [], set()
    for item in obj['lines']:
        if not isinstance(item, dict):
            raise ValueError('Every manifest line must be an object')
        r = dict(item)
        ident = r.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', ident) or ident in ids:
            raise ValueError(f'Unsafe/duplicate ID: {ident}')
        ids.add(ident)
        if r.get('status', 'ready') not in ('ready', 'reviewed'):
            continue
        if r.get('blockers'):
            raise ValueError(f'Ready line has unresolved blockers: {ident}')
        if not all(isinstance(r.get(k), str) and r[k].strip() for k in ('speaker', 'text', 'reference')):
            raise ValueError(f'Missing speaker/text/reference: {ident}')
        for key in ('reference', 'original'):
            if r.get(key):
                r[key] = str((path.parent / r[key]).resolve())
                if not Path(r[key]).is_file():
                    raise ValueError(f'Missing {key}: {r[key]}')
        fmt = r.get('format', {})
        if not isinstance(fmt, dict) or any(type(fmt.get(k)) is not int or fmt[k] <= 0 for k in ('sample_rate', 'channels', 'frames')):
            raise ValueError(f'Expected positive integer format sample_rate/channels/frames: {ident}')
        if fmt['channels'] > 8:
            raise ValueError('More than 8 channels is unsupported')
        if args.ids and ident not in args.ids.split(','):
            continue
        if args.scene and r.get('scene') != args.scene:
            continue
        rows.append(r)
    if args.ids and set(args.ids.split(',')) - {r['id'] for r in rows}:
        raise ValueError('Requested IDs missing, excluded or filtered')
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise ValueError('No eligible dialogue selected')
    return rows


def model_identity(args):
    model = Path(args.model)
    if model.is_dir():
        files = sorted(p for p in model.rglob('*') if p.is_file())
        return {'files': {str(p.relative_to(model)): digest(p) for p in files}}
    if args.adapter == 'qwen':
        raise ValueError('--model must be a local model directory; download explicitly before generation')
    return {'name': args.model}


def config(args):
    keys = ('adapter', 'model', 'device', 'dtype', 'attention', 'language', 'seed', 'max_new_tokens', 'batch_size')
    cfg = {k: getattr(args, k) for k in keys}
    cfg['adapter_options'] = args.adapter_options
    cfg['model_identity'] = model_identity(args)
    packages = ['numpy', 'soundfile'] + (['qwen-tts', 'torch', 'transformers'] if args.adapter == 'qwen' else [])
    cfg['versions'] = {p: importlib.metadata.version(p) for p in packages}
    if ':' in args.adapter and args.adapter != 'qwen':
        spec = importlib.util.find_spec(args.adapter.partition(':')[0])
        if not spec or not spec.origin:
            raise ValueError('Custom adapter must have a source file')
        cfg['adapter_sha256'] = digest(spec.origin)
    cfg['pipeline_version'] = 1
    cfg['implementation_sha256'] = digest(Path(__file__))
    cfg['builtin_adapters_sha256'] = digest(Path(__file__).parent / 'adapters' / 'tts.py')
    return cfg


def raw_key(row, cfg, group):
    return fingerprint({'text': row['text'], 'speaker': row['speaker'],
                        'reference': digest(row['reference']), 'config': cfg,
                        'batch': [r['id'] for r in group]})


def valid(path, key):
    try:
        meta = read(path.with_suffix('.json'))
        if meta['fingerprint'] != key or meta['sha256'] != digest(path):
            return False
        audio(path)
        return True
    except (OSError, ValueError, KeyError, RuntimeError):
        return False


def event(out, phase, **fields):
    data = {'time': time.time(), 'phase': phase, **fields}
    write(out / 'status.json', data)
    with (out / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')
    print(json.dumps(data, ensure_ascii=False), flush=True)


@contextlib.contextmanager
def report_errors(out):
    try:
        yield
    except Exception as exc:
        event(out, 'failed', failed=1, error=str(exc))
        raise


def generate(rows, args, out, cfg):
    import numpy as np
    import soundfile as sf
    from .adapters.tts import create
    adapter = None
    write(out / 'generation-config.json', cfg)
    started, generated, skipped = time.monotonic(), 0, 0
    for offset in range(0, len(rows), args.batch_size):
        if (out / 'STOP').exists():
            event(out, 'stopped', done=generated, skipped=skipped, total=len(rows))
            return
        group = rows[offset:offset + args.batch_size]
        paths = [out / 'raw' / (r['id'] + '.wav') for r in group]
        keys = [raw_key(r, cfg, group) for r in group]
        if all(valid(p, k) for p, k in zip(paths, keys)):
            skipped += len(group)
            continue
        # Regenerate the whole original batch to retain batch composition on resume.
        if adapter is None:
            event(out, 'loading_model')
            adapter = create(args.adapter)
            adapter.load(cfg)
            started = time.monotonic()
        results = adapter.synthesize(group, cfg)
        if len(results) != len(group):
            raise ValueError('Adapter returned wrong result count')
        with tempfile.TemporaryDirectory(dir=out) as temp:
            staged = []
            for r, (samples, rate), dest, key in zip(group, results, paths, keys):
                a = np.asarray(samples)
                if a.ndim not in (1, 2) or not a.size or not np.isfinite(a).all() or int(rate) <= 0:
                    raise ValueError('Invalid adapter waveform: ' + r['id'])
                if float(np.max(np.abs(a))) >= 1:
                    raise ValueError('Adapter waveform would clip PCM output: ' + r['id'])
                p = Path(temp) / dest.name
                sf.write(p, a, int(rate), subtype='PCM_16')
                audio(p)
                staged.append((p, dest, key, r))
            # Only commit after every item in the batch validates.
            for p, dest, key, r in staged:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(p, dest)
                write(dest.with_suffix('.json'), {'fingerprint': key, 'sha256': digest(dest),
                      'quality': 'test_tone' if args.adapter == 'mock' else 'needs_listening',
                      'text': r['text'], 'speaker': r['speaker']})
        generated += len(group)
        elapsed = max(time.monotonic() - started, 1e-6)
        event(out, 'generating', done=generated + skipped, total=len(rows), skipped=skipped,
              failed=0, scene=group[-1].get('scene'), elapsed=elapsed,
              lines_per_minute=generated / elapsed * 60,
              eta_seconds=(len(rows) - generated - skipped) * elapsed / generated)
    event(out, 'generated', done=len(rows), total=len(rows), skipped=skipped, failed=0)


def fit_key(row, args, raw):
    return fingerprint({'raw': digest(raw), 'format': row['format'],
                        'original': digest(row['original']) if row.get('original') else None,
                        'options': {k: getattr(args, k) for k in
                                    ('timing', 'loudness', 'gain_db', 'peak_db', 'max_speedup', 'ffmpeg')}})


def fit(rows, args, out):
    import numpy as np
    import soundfile as sf
    for r in rows:
        raw = out / 'raw' / (r['id'] + '.wav')
        a, rate = audio(raw)
        fmt = r['format']
        target = fmt['frames'] / fmt['sample_rate']
        ratio = len(a) / rate / target
        if args.timing == 'pad' and ratio > 1 + 1e-6:
            raise ValueError('Audio exceeds target in pad mode: ' + r['id'])
        tempo = max(1., ratio) if args.timing == 'speedup' else 1.
        if tempo > args.max_speedup:
            raise ValueError(f"Excessive speedup {tempo:.2f}: {r['id']}; edit text or change explicit limit")
        filters = [f'rubberband=tempo={tempo}:pitch=1:formant=preserved'] if tempo > 1 else []
        with tempfile.TemporaryDirectory(dir=out) as temp:
            converted = Path(temp) / 'converted.wav'
            cmd = [args.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(raw)]
            if filters:
                cmd += ['-af', ','.join(filters)]
            cmd += ['-ar', str(fmt['sample_rate']), '-ac', str(fmt['channels']), '-c:a', 'pcm_f32le', str(converted)]
            subprocess.run(cmd, check=True, capture_output=True)
            a, rate = audio(converted)
            if args.timing != 'none':
                a = np.pad(a[:fmt['frames']], ((0, max(0, fmt['frames'] - len(a))), (0, 0)))
            gain = 10 ** (args.gain_db / 20)
            if args.loudness == 'original':
                if not r.get('original'):
                    raise ValueError('original loudness requires original WAV: ' + r['id'])
                original, original_rate = audio(r['original'])
                if original.shape != (fmt['frames'], fmt['channels']) or original_rate != fmt['sample_rate']:
                    raise ValueError('Original format disagrees with manifest: ' + r['id'])
                gain *= float(np.sqrt(np.mean(original.astype('float64') ** 2)) /
                              np.sqrt(np.mean(a.astype('float64') ** 2)))
            gain = min(gain, 10 ** (args.peak_db / 20) / float(np.max(np.abs(a))))
            final = Path(temp) / 'final.wav'
            sf.write(final, a * gain, rate, subtype='PCM_16')
            audio(final)
            dest = out / 'fitted' / raw.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(final, dest)
            write(dest.with_suffix('.json'), {'fingerprint': fit_key(r, args, raw),
                  'sha256': digest(dest), 'tempo': tempo, 'gain': gain, 'timing': args.timing})
    event(out, 'fitted', done=len(rows), total=len(rows))


def verify(rows, args, out, cfg):
    report = []
    for offset in range(0, len(rows), args.batch_size):
        group = rows[offset:offset + args.batch_size]
        for r in group:
            raw = out / 'raw' / (r['id'] + '.wav')
            if not valid(raw, raw_key(r, cfg, group)):
                raise ValueError('Stale or invalid raw: ' + r['id'])
            path = out / 'fitted' / raw.name
            if not valid(path, fit_key(r, args, raw)):
                raise ValueError('Stale or invalid fit: ' + r['id'])
            a, rate = audio(path)
            fmt = r['format']
            if rate != fmt['sample_rate'] or a.shape[1] != fmt['channels']:
                raise ValueError('Format mismatch: ' + r['id'])
            if args.timing != 'none' and len(a) != fmt['frames']:
                raise ValueError('Frame mismatch: ' + r['id'])
            report.append({'id': r['id'], 'file': 'audio/' + path.name, 'sha256': digest(path),
                           'frames': len(a), 'sample_rate': rate, 'channels': a.shape[1],
                           'speaker': r['speaker'], 'text': r['text'], 'scene': r.get('scene')})
    selected_ids = {r['id'] for r in rows}
    all_rows = read(args.manifest)['lines']
    excluded = [{'id': r['id'], 'status': r.get('status', 'ready'),
                 'reason': r.get('reason', 'outside selection or not eligible')}
                for r in all_rows if r['id'] not in selected_ids]
    receipt = {'schema_version': 1, 'scope': 'selected_manifest_lines', 'count': len(rows),
               'in_game_verified': False, 'perceptual_qa': 'pending',
               'test_tones': args.adapter == 'mock', 'timing': args.timing, 'files': report,
               'manifest_sha256': digest(args.manifest), 'excluded': excluded,
               'synthesis': {k: v for k, v in cfg.items() if k != 'model'}}
    write(out / 'verification.json', receipt)
    return receipt


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['doctor', 'plan', 'generate', 'fit', 'verify', 'preview', 'package'])
    p.add_argument('--manifest', default='examples/demo/manifest.json')
    p.add_argument('--output', default='work/demo')
    p.add_argument('--adapter', default='qwen', help='qwen, mock or trusted module:Class')
    p.add_argument('--adapter-options', type=json.loads, default={}, help='JSON object of model-specific generation options')
    p.add_argument('--config', help='JSON object of CLI defaults; explicit flags override it')
    p.add_argument('--model', default='models/tts')
    p.add_argument('--device', default='cuda:0')
    p.add_argument('--dtype', choices=['float32', 'float16', 'bfloat16'], default='bfloat16')
    p.add_argument('--attention', default='sdpa')
    p.add_argument('--language', default='Russian')
    p.add_argument('--batch-size', type=int, default=4)
    p.add_argument('--preset', choices=['optimized', 'preview'], default='optimized',
                   help='preview: batch=1, seed=42, max tokens=384; processing unchanged')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--max-new-tokens', type=int, default=1024)
    p.add_argument('--ids', help='Comma-separated exact IDs')
    p.add_argument('--scene')
    p.add_argument('--limit', type=int)
    p.add_argument('--timing', choices=['speedup', 'pad', 'none'], default='speedup')
    p.add_argument('--loudness', choices=['original', 'none'], default='original')
    p.add_argument('--gain-db', type=float, default=0)
    p.add_argument('--peak-db', type=float, default=-1)
    p.add_argument('--max-speedup', type=float, default=2)
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--lock-dir', default=str(Path.home() / '.cache' / 'universal-dubbing'))
    p.add_argument('--allow-download', action='store_true', help='Allow dependency network access; model path still local')
    p.add_argument('--dry-run', action='store_true')
    return p


def main(argv=None):
    p = parser()
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument('--config')
    settings, _ = preliminary.parse_known_args(argv)
    if settings.config:
        try:
            defaults = read(settings.config)
            allowed = {a.dest for a in p._actions} - {'command', 'help', 'config'}
            if not isinstance(defaults, dict) or set(defaults) - allowed:
                raise ValueError('Config must be an object with known CLI option names (underscores)')
            flags = []
            for key, value in defaults.items():
                flag = '--' + key.replace('_', '-')
                if key in ('allow_download', 'dry_run'):
                    if type(value) is not bool:
                        raise ValueError('Config boolean required: ' + key)
                    if value:
                        flags.append(flag)
                else:
                    flags.extend([flag, json.dumps(value) if key == 'adapter_options' else str(value)])
            parsed = p.parse_args(['plan', *flags])
            p.set_defaults(**{key: getattr(parsed, key) for key in defaults})
        except (ValueError, OSError) as exc:
            p.error(str(exc))
    args = p.parse_args(argv)
    if args.preset == 'preview':
        args.batch_size, args.seed, args.max_new_tokens = 1, 42, 384
    try:
        if not isinstance(args.adapter_options, dict):
            raise ValueError('--adapter-options must be a JSON object')
        if args.batch_size < 1 or args.max_new_tokens < 1 or (args.limit is not None and args.limit < 1):
            raise ValueError('Batch size, token limit and selection limit must be positive')
        if not 0 <= args.seed < 2**32:
            raise ValueError('Seed must be in [0, 2**32)')
        if not all(math.isfinite(v) for v in (args.gain_db, args.peak_db, args.max_speedup)) or args.peak_db >= 0 or args.max_speedup < 1:
            raise ValueError('Finite gains, peak < 0 and max-speedup >= 1 required')
        if args.command == 'doctor':
            print(json.dumps(diagnose(args.ffmpeg), indent=2))
            return 0
        rows = load_manifest(args)
        out = Path(args.output).resolve()
        if args.command == 'plan' or args.dry_run:
            all_rows = read(args.manifest)['lines']
            selected_ids = {r['id'] for r in rows}
            print(json.dumps({'command': args.command, 'output': str(out), 'total': len(rows),
                              'ids': [r['id'] for r in rows], 'adapter': args.adapter,
                              'excluded': [{'id': r['id'], 'status': r.get('status', 'ready')}
                                           for r in all_rows if r['id'] not in selected_ids]}, ensure_ascii=False, indent=2))
            return 0
        out.mkdir(parents=True, exist_ok=True)
        cache = out.parent / 'cache'
        for key, folder in [('HF_HOME', 'huggingface'), ('TORCH_HOME', 'torch'), ('NUMBA_CACHE_DIR', 'numba')]:
            os.environ.setdefault(key, str(cache / folder))
        os.environ['HF_HUB_OFFLINE'] = '0' if args.allow_download else '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '0' if args.allow_download else '1'
        with locked(out / 'RUNNING.lock'), report_errors(out):
            cfg = config(args)
            if args.command == 'generate':
                resource = re.sub(r'[^A-Za-z0-9_-]', '_', args.device)
                with locked(Path(args.lock_dir) / (resource + '.lock')):
                    generate(rows, args, out, cfg)
            elif args.command == 'fit':
                # Refuse processing stale synthesis before any fitted output changes.
                for i in range(0, len(rows), args.batch_size):
                    group = rows[i:i + args.batch_size]
                    if not all(valid(out / 'raw' / (r['id'] + '.wav'), raw_key(r, cfg, group)) for r in group):
                        raise ValueError('Missing/stale raw batch; run generate with the same synthesis options')
                fit(rows, args, out)
            else:
                receipt = verify(rows, args, out, cfg)
                if args.command == 'preview':
                    body = ['<!doctype html><meta charset="utf-8"><title>Dialogue review</title><h1>Listening review</h1>']
                    for r in rows:
                        ident = html.escape(r['id'])
                        body.append(f'<h2>{ident} — {html.escape(r["speaker"])}</h2><p>{html.escape(r["text"])}</p><audio controls src="fitted/{ident}.wav"></audio>')
                    (out / 'listen.html').write_text('\n'.join(body), encoding='utf-8')
                elif args.command == 'package':
                    dest = out / 'audio-export.zip'
                    with tempfile.NamedTemporaryFile(dir=out, suffix='.zip', delete=False) as f:
                        temp = Path(f.name)
                    try:
                        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
                            z.writestr('manifest.json', json.dumps(receipt, ensure_ascii=False, indent=2))
                            for r in rows:
                                z.write(out / 'fitted' / (r['id'] + '.wav'), 'audio/' + r['id'] + '.wav')
                        os.replace(temp, dest)
                    finally:
                        temp.unlink(missing_ok=True)
                    write(out / 'package.json', {'sha256': digest(dest), 'bytes': dest.stat().st_size,
                                                'kind': 'portable_wav_export', 'count': len(rows)})
            return 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr)
        p.exit(2, f'Error: {exc}\n')
    except KeyboardInterrupt:
        p.exit(130, 'Interrupted; validated raw batches remain resumable.\n')
