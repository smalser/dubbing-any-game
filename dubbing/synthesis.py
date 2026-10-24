"""Content-addressed synthesis batches with a final commit receipt.

The receipt is written last. Interrupted commits cannot pass verification, even
when all per-line metadata happened to be written before the interruption.
"""
import importlib.metadata
import importlib.util
import numbers
import os
from pathlib import Path
import re
import tempfile
import time

from .audio import audio
from .storage import digest, event, fingerprint, read, write


def model_identity(args):
    model = Path(args.model)
    if model.is_dir():
        files = sorted(p for p in model.rglob('*') if p.is_file()
                       and '.cache' not in p.relative_to(model).parts)
        if not files:
            raise ValueError('Model directory is empty')
        return {'files': {p.relative_to(model).as_posix(): digest(p) for p in files}}
    if args.adapter == 'qwen':
        raise ValueError('--model must be a local model directory; download explicitly before generation')
    return {'name': args.model}


def config(args):
    keys = ('adapter', 'model', 'device', 'dtype', 'attention', 'language', 'seed', 'max_new_tokens', 'batch_size')
    cfg = {k: getattr(args, k) for k in keys}
    cfg['adapter_options'] = args.adapter_options
    cfg['model_identity'] = model_identity(args)
    packages = ['numpy', 'soundfile'] + (['qwen-tts', 'torch', 'transformers'] if args.adapter == 'qwen' else [])
    try:
        cfg['versions'] = {p: importlib.metadata.version(p) for p in packages}
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError(f'Missing runtime dependency: {exc.name}; install the project and adapter extra') from exc
    if args.adapter not in ('mock', 'qwen'):
        module, sep, cls = args.adapter.partition(':')
        if not sep or not module or not cls:
            raise ValueError('Adapter must be mock, qwen or trusted module:Class')
        spec = importlib.util.find_spec(module)
        if not spec or not spec.origin or not Path(spec.origin).is_file():
            raise ValueError('Custom adapter must have a readable source file')
        cfg['adapter_sha256'] = digest(spec.origin)
    cfg['cache_schema'] = 2
    cfg['implementation_sha256'] = digest(Path(__file__))
    cfg['builtin_adapters_sha256'] = digest(Path(__file__).parent / 'adapters' / 'tts.py')
    return cfg


def group_key(cfg, group):
    # Absolute model location is operational, not synthesis content.
    settings = {k: v for k, v in cfg.items() if k != 'model'}
    return fingerprint({'config': settings, 'rows': [
        {'id': r['id'], 'text': r['text'], 'speaker': r['speaker'], 'reference': digest(r['reference'])}
        for r in group]})


def raw_key(row, cfg, group):
    return fingerprint({'id': row['id'], 'batch': group_key(cfg, group)})


def valid(path, key):
    try:
        meta = read(path.with_suffix('.json'))
        if not isinstance(meta, dict) or meta.get('fingerprint') != key or meta.get('sha256') != digest(path):
            return False
        audio(path)
        return True
    except (OSError, ValueError, RuntimeError, TypeError):
        return False


def batch_path(out, group):
    return out / 'batches' / (fingerprint([r['id'] for r in group]) + '.json')


def valid_batch(out, cfg, group):
    try:
        receipt = read(batch_path(out, group))
        if not isinstance(receipt, dict) or receipt.get('fingerprint') != group_key(cfg, group):
            return False
        expected = {r['id']: digest(out / 'raw' / (r['id'] + '.wav')) for r in group}
        return receipt.get('files') == expected and all(
            valid(out / 'raw' / (r['id'] + '.wav'), raw_key(r, cfg, group)) for r in group)
    except (OSError, ValueError, RuntimeError, TypeError):
        return False


def require_raw(rows, args, out, cfg):
    for i in range(0, len(rows), args.batch_size):
        if not valid_batch(out, cfg, rows[i:i + args.batch_size]):
            raise ValueError('Missing, stale or uncommitted raw batch; run generate with the same selection and synthesis options')


def resource_name(device):
    # These aliases identify the same default CUDA device in one visibility map.
    if device == 'cuda':
        device = 'cuda:0'
    elif re.fullmatch(r'cuda:[0-9]+', device):
        device = 'cuda:' + str(int(device.split(':')[1]))
    return re.sub(r'[^A-Za-z0-9_-]', '_', device)


def generate(rows, args, out, cfg):
    import numpy as np
    import soundfile as sf
    from .adapters.tts import create
    adapter = None
    generated, skipped = 0, 0
    synthesis_seconds = 0.
    started = time.monotonic()
    write(out / 'generation-config.json', cfg)
    reference_hashes = {r['reference']: digest(r['reference']) for r in rows}

    def stopped():
        if not (out / 'STOP').exists():
            return False
        event(out, 'stopped', done=generated + skipped, generated=generated, skipped=skipped,
              total=len(rows), elapsed=time.monotonic() - started, resumable=True)
        return True

    for offset in range(0, len(rows), args.batch_size):
        if stopped():
            return False
        group = rows[offset:offset + args.batch_size]
        if any(digest(r['reference']) != reference_hashes[r['reference']] for r in group):
            raise ValueError('Reference changed during this run; restart generation with stable inputs')
        if valid_batch(out, cfg, group):
            skipped += len(group)
            continue
        if adapter is None:
            # Validate reusable reference WAVs before loading expensive model weights.
            for reference in {r['reference'] for r in rows}:
                audio(reference)
            event(out, 'loading_model', done=skipped, total=len(rows), skipped=skipped)
            adapter = create(args.adapter)
            adapter.load(cfg)
            if stopped():
                return False
        key = group_key(cfg, group)
        keys = [raw_key(r, cfg, group) for r in group]
        synthesis_start = time.monotonic()
        # Keep the adapter's input contract identical to what the cache hashes.
        requests = [{k: r[k] for k in ('id', 'text', 'speaker', 'reference')} for r in group]
        results = adapter.synthesize(requests, cfg)
        synthesis_seconds += time.monotonic() - synthesis_start
        if not isinstance(results, (list, tuple)) or len(results) != len(group):
            raise ValueError('Adapter must return one (samples, integer sample_rate) pair per row')
        # Refuse to attribute generated audio to references edited during synthesis.
        if group_key(cfg, group) != key:
            raise ValueError('Reference changed during synthesis; batch was not committed')
        with tempfile.TemporaryDirectory(dir=out) as temp:
            staged = []
            for r, result, item_key in zip(group, results, keys):
                if not isinstance(result, (tuple, list)) or len(result) != 2:
                    raise ValueError('Invalid adapter result pair: ' + r['id'])
                samples, rate = result
                if isinstance(rate, bool) or not isinstance(rate, numbers.Integral) or rate <= 0:
                    raise ValueError('Adapter sample rate must be a positive integer: ' + r['id'])
                a = np.asarray(samples)
                if (a.dtype.kind not in 'fiu' or a.ndim not in (1, 2) or not a.size
                        or (a.ndim == 2 and not 1 <= a.shape[1] <= 8) or not np.isfinite(a).all()):
                    raise ValueError('Invalid adapter waveform: ' + r['id'])
                if float(np.max(np.abs(a.astype('float64')))) >= 1:
                    raise ValueError('Adapter waveform would clip PCM output: ' + r['id'])
                dest = out / 'raw' / (r['id'] + '.wav')
                p = Path(temp) / dest.name
                # Float samples are normalized amplitudes, including integer arrays.
                sf.write(p, a.astype('float32'), int(rate), subtype='PCM_16')
                audio(p)
                staged.append((p, dest, item_key, r))
            # Invalidate the old transaction before touching its constituent files.
            receipt_path = batch_path(out, group)
            receipt_path.unlink(missing_ok=True)
            hashes = {}
            for p, dest, item_key, r in staged:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(p, dest)
                hashes[r['id']] = digest(dest)
                write(dest.with_suffix('.json'), {'fingerprint': item_key, 'sha256': hashes[r['id']],
                      'quality': 'test_tone' if args.adapter == 'mock' else 'needs_listening',
                      'text': r['text'], 'speaker': r['speaker']})
            write(receipt_path, {'fingerprint': key, 'files': hashes})
        generated += len(group)
        event(out, 'generating', done=generated + skipped, total=len(rows), skipped=skipped,
              generated=generated, failed=0, scene=group[-1].get('scene'), elapsed=time.monotonic() - started,
              synthesis_seconds=synthesis_seconds,
              synthesis_lines_per_minute=generated / max(synthesis_seconds, 1e-6) * 60,
              estimated_synthesis_remaining_seconds=(len(rows) - generated - skipped) * synthesis_seconds / generated)
    event(out, 'generated', done=len(rows), total=len(rows), generated=generated, skipped=skipped, failed=0,
          elapsed=time.monotonic() - started, synthesis_seconds=synthesis_seconds)
    return True
