"""Audio fitting and verification, independently versioned from neural synthesis."""
import importlib.metadata
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .audio import audio
from .manifest import exclusions
from .storage import digest, event, fingerprint, write
from .synthesis import require_raw, valid


def processing_identity(args):
    if not hasattr(args, '_processing_identity'):
        executable = shutil.which(args.ffmpeg)
        if not executable:
            raise ValueError('FFmpeg not found: ' + args.ffmpeg)
        try:
            version = subprocess.run([executable, '-version'], check=True, capture_output=True,
                                     text=True, encoding='utf-8', errors='replace', timeout=10).stdout
        except subprocess.TimeoutExpired as exc:
            raise ValueError('FFmpeg version check timed out') from exc
        args._processing_identity = {
            'implementation': digest(Path(__file__)),
            'audio_validation': digest(Path(__file__).with_name('audio.py')),
            'ffmpeg_sha256': digest(executable),
            # A PATH executable can be a launcher/shim; record the invoked build too.
            'ffmpeg_version': version.strip(),
            'versions': {p: importlib.metadata.version(p) for p in ('numpy', 'soundfile')},
        }
    return args._processing_identity


def fit_key(row, args, raw):
    return fingerprint({'raw': digest(raw), 'format': row['format'],
                        'original': digest(row['original']) if args.loudness == 'original' and row.get('original') else None,
                        'implementation': processing_identity(args),
                        'options': {k: getattr(args, k) for k in
                                    ('timing', 'loudness', 'gain_db', 'peak_db', 'max_speedup')}})


def fit(rows, args, out):
    import numpy as np
    import soundfile as sf
    processing_identity(args)
    # Validate every required original before replacing any fitted output.
    if args.loudness == 'original':
        for r in rows:
            if not r.get('original'):
                raise ValueError('original loudness requires original WAV: ' + r['id'])
            original, rate = audio(r['original'])
            fmt = r['format']
            if original.shape != (fmt['frames'], fmt['channels']) or rate != fmt['sample_rate']:
                raise ValueError('Original format disagrees with manifest: ' + r['id'])
    skipped = 0
    for r in rows:
        raw = out / 'raw' / (r['id'] + '.wav')
        dest = out / 'fitted' / raw.name
        key = fit_key(r, args, raw)
        if valid(dest, key):
            skipped += 1
            continue
        a, rate = audio(raw)
        fmt = r['format']
        target = fmt['frames'] / fmt['sample_rate']
        ratio = len(a) / rate / target
        if args.timing == 'pad' and ratio > 1 + 1e-6:
            raise ValueError('Audio exceeds target in pad mode: ' + r['id'])
        tempo = max(1., ratio) if args.timing == 'speedup' else 1.
        if tempo > args.max_speedup:
            raise ValueError(f"Excessive speedup {tempo:.2f}: {r['id']}; edit text or change explicit limit")
        with tempfile.TemporaryDirectory(dir=out) as temp:
            converted = Path(temp) / 'converted.wav'
            cmd = [args.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(raw)]
            if tempo > 1:
                cmd += ['-af', f'rubberband=tempo={tempo}:pitch=1:formant=preserved']
            cmd += ['-ar', str(fmt['sample_rate']), '-ac', str(fmt['channels']), '-c:a', 'pcm_f32le', str(converted)]
            subprocess.run(cmd, check=True, capture_output=True)
            a, rate = audio(converted, pcm_range=False)
            if args.timing != 'none':
                a = np.pad(a[:fmt['frames']], ((0, max(0, fmt['frames'] - len(a))), (0, 0)))
            a = a.astype('float64')
            energy = float(np.mean(a ** 2))
            if energy <= 0:
                raise ValueError('Fitting produced silence: ' + r['id'])
            gain = 10 ** (args.gain_db / 20)
            if args.loudness == 'original':
                original, _ = audio(r['original'])
                gain *= math.sqrt(float(np.mean(original.astype('float64') ** 2)) / energy)
            # Exact PCM16-representable bound prevents quantization exceeding the cap.
            cap = math.floor(10 ** (args.peak_db / 20) * 32768) / 32768
            if cap <= 0:
                raise ValueError('peak-db is below the smallest nonzero PCM16 sample')
            gain = min(gain, cap / float(np.max(np.abs(a))))
            final = Path(temp) / 'final.wav'
            sf.write(final, np.clip(a * gain, -cap, cap), rate, subtype='PCM_16')
            final_audio, _ = audio(final)
            if float(np.max(np.abs(final_audio))) > 10 ** (args.peak_db / 20) + 1e-7:
                raise ValueError('PCM peak exceeds configured limit: ' + r['id'])
            if fit_key(r, args, raw) != key:
                raise ValueError('Audio input changed during fit: ' + r['id'])
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(final, dest)
            write(dest.with_suffix('.json'), {'fingerprint': key, 'sha256': digest(dest),
                  'tempo': tempo, 'gain': gain, 'timing': args.timing})
    event(out, 'fitted', done=len(rows), total=len(rows), skipped=skipped, failed=0)


def verify(rows, args, out, cfg):
    import numpy as np
    require_raw(rows, args, out, cfg)
    report = []
    for r in rows:
        raw = out / 'raw' / (r['id'] + '.wav')
        path = out / 'fitted' / raw.name
        if not valid(path, fit_key(r, args, raw)):
            raise ValueError('Stale or invalid fit: ' + r['id'])
        a, rate = audio(path)
        fmt = r['format']
        if rate != fmt['sample_rate'] or a.shape[1] != fmt['channels']:
            raise ValueError('Format mismatch: ' + r['id'])
        if args.timing != 'none' and len(a) != fmt['frames']:
            raise ValueError('Frame mismatch: ' + r['id'])
        peak = float(np.max(np.abs(a)))
        if peak > 10 ** (args.peak_db / 20) + 1e-7:
            raise ValueError('Peak limit exceeded: ' + r['id'])
        report.append({'id': r['id'], 'file': 'audio/' + path.name, 'sha256': digest(path),
                       'frames': len(a), 'sample_rate': rate, 'channels': a.shape[1], 'peak': peak,
                       'speaker': r['speaker'], 'text': r['text'], 'scene': r.get('scene')})
    receipt = {'schema_version': 1, 'scope': 'selected_manifest_lines', 'count': len(rows),
               'in_game_verified': False, 'perceptual_qa': 'pending',
               'test_tones': args.adapter == 'mock', 'timing': args.timing, 'files': report,
               'manifest_sha256': digest(args.manifest), 'excluded': exclusions(args, rows),
               'synthesis': {k: v for k, v in cfg.items() if k != 'model'},
               'processing': processing_identity(args)}
    write(out / 'verification.json', receipt)
    event(out, 'verified', done=len(rows), total=len(rows), failed=0)
    return receipt
