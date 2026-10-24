"""Manifest-driven dialogue synthesis, audio fitting and verified WAV export."""
import argparse
import html
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from .manifest import exclusions, load_manifest
from .platforms import diagnose
from .processing import fit, verify
from .storage import digest, event, locked, parse_json, read, report_errors, write
from .synthesis import config, generate, require_raw, resource_name


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['doctor', 'plan', 'generate', 'fit', 'verify', 'preview', 'package'])
    p.add_argument('--manifest', default='examples/demo/manifest.json')
    p.add_argument('--output', default='work/demo')
    p.add_argument('--adapter', default='qwen', help='qwen, mock or trusted module:Class')
    p.add_argument('--adapter-options', type=parse_json, default={}, help='JSON object of model-specific generation options')
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
    p.add_argument('--game-tools', action=argparse.BooleanOptionalAction, default=False,
                   help='Check the pinned Universal Modder requirement in doctor')
    p.add_argument('--lock-dir', default=str(Path.home() / '.cache' / 'universal-dubbing'))
    p.add_argument('--allow-download', action=argparse.BooleanOptionalAction, default=False,
                   help='Allow dependency network access; model path still local')
    p.add_argument('--dry-run', action=argparse.BooleanOptionalAction, default=False)
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
                if key in ('allow_download', 'dry_run', 'game_tools'):
                    if type(value) is not bool:
                        raise ValueError('Config boolean required: ' + key)
                    if value:
                        flags.append(flag)
                else:
                    numeric = {'batch_size': int, 'seed': int, 'max_new_tokens': int, 'limit': int,
                               'gain_db': float, 'peak_db': float, 'max_speedup': float}
                    if key == 'adapter_options':
                        if not isinstance(value, dict):
                            raise ValueError('Config adapter_options must be an object')
                    elif key in numeric:
                        accepted = (int, float) if numeric[key] is float else (int,)
                        if type(value) not in accepted:
                            raise ValueError('Config numeric value required: ' + key)
                    elif not isinstance(value, str) or not value.strip():
                        raise ValueError('Config nonempty string required: ' + key)
                    # Equals syntax permits string values starting with a hyphen.
                    flags.append(flag + '=' + (json.dumps(value, allow_nan=False) if key == 'adapter_options' else str(value)))
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
        json.dumps(args.adapter_options, allow_nan=False)
        if args.batch_size < 1 or args.max_new_tokens < 1 or (args.limit is not None and args.limit < 1):
            raise ValueError('Batch size, token limit and selection limit must be positive')
        if not 0 <= args.seed < 2**32:
            raise ValueError('Seed must be in [0, 2**32)')
        if (not all(math.isfinite(v) for v in (args.gain_db, args.peak_db, args.max_speedup))
                or not -96 < args.peak_db < 0 or abs(args.gain_db) > 120 or args.max_speedup < 1):
            raise ValueError('Finite values required: -96 < peak-db < 0, abs(gain-db) <= 120, max-speedup >= 1')
        if math.floor(10 ** (args.peak_db / 20) * 32768) < 1:
            raise ValueError('peak-db must allow a nonzero PCM16 sample (at least about -90.30 dBFS)')
        if args.command == 'doctor':
            report = diagnose(args)
            print(json.dumps(report, indent=2))
            return 0 if report['ready_for_requested_checks'] else 2
        rows = load_manifest(args)
        out = Path(args.output).resolve()
        sources = {Path(r[k]).resolve() for r in rows for k in ('reference', 'original') if k in r}
        sources.add(Path(args.manifest).resolve())
        if args.config:
            sources.add(Path(args.config).resolve())
        reserved = {'status.json', 'events.jsonl', 'generation-config.json', 'verification.json',
                    'package.json', 'audio-export.zip', 'listen.html', 'RUNNING.lock', 'STOP'}
        for source in sources:
            if (source.parent == out and source.name in reserved
                    or any(source.is_relative_to((out / folder).resolve()) for folder in ('raw', 'fitted', 'batches'))):
                raise ValueError(f'Input overlaps generated output: {source}; choose a separate --output')
        if args.command == 'plan' or args.dry_run:
            print(json.dumps({'command': args.command, 'output': str(out), 'total': len(rows),
                              'ids': [r['id'] for r in rows], 'adapter': args.adapter,
                              'excluded': exclusions(args, rows)}, ensure_ascii=False, indent=2))
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
                resource = resource_name(args.device)
                with locked(Path(args.lock_dir) / (resource + '.lock')):
                    if not generate(rows, args, out, cfg):
                        return 3
            elif args.command == 'fit':
                require_raw(rows, args, out, cfg)
                fit(rows, args, out)
            else:
                receipt = verify(rows, args, out, cfg)
                if args.command == 'preview':
                    body = ['<!doctype html><meta charset="utf-8"><title>Dialogue review</title><h1>Listening review</h1>']
                    for r in rows:
                        ident = html.escape(r['id'])
                        body.append(f'<h2>{ident} — {html.escape(r["speaker"])}</h2><p>{html.escape(r["text"])}</p><audio controls src="fitted/{ident}.wav"></audio>')
                    (out / 'listen.html').write_text('\n'.join(body), encoding='utf-8')
                    event(out, 'previewed', done=len(rows), total=len(rows), file='listen.html')
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
                    event(out, 'packaged', done=len(rows), total=len(rows), file=dest.name)
            return 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr)
        p.exit(2, f'Error: {exc}\n')
    except KeyboardInterrupt:
        p.exit(130, 'Interrupted; validated raw batches remain resumable.\n')
