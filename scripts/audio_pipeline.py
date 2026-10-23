"""CPU-only audio fitting, Wwise packaging and explicit installation.

mode speedup (default): never slow speech; accelerate overlong audio, pad short.
mode both: accelerate or slow to original duration (legacy/experimental).
mode pad: natural tempo plus silence; reject overlong speech, never truncate it.
mode none: no tempo or duration fitting; retain variable duration (sync may differ).
All modes optionally trim boundary silence, preserve internal pauses, convert to
original sample rate/channel count and normalize gain. No GPU calls on import.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import soundfile as sf


def _emit(progress, event, **fields):
    if progress:
        progress(event, **fields)


def _json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temp, path)


def _inside(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if target == root or root not in target.parents:
        raise ValueError(f'Path escapes its root: {relative}')
    return target


def _rows(rows):
    rows = list(rows)
    if not rows:
        raise ValueError('No ready rows selected')
    ids = [str(r['id']) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate row IDs')
    if any(not x or any(c not in '0123456789abcdefABCDEF_-' for c in x) for x in ids):
        raise ValueError('Unsafe row ID')
    return rows


def _run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            encoding='utf8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {args[0]}\n'
                           + result.stderr[-4000:] + result.stdout[-2000:])
    return result.stdout


def _ffmpeg(root):
    candidates = [Path(root) / 'work/tools/ffmpeg/ffmpeg.exe',
                  Path('C:/ProgramData/chocolatey/bin/ffmpeg.exe')]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which('ffmpeg')
    if not found:
        raise FileNotFoundError('ffmpeg with Rubber Band filter is required')
    return found


def _trim_bounds(audio, sr):
    step = max(1, sr // 200)
    n = len(audio) // step
    if not n:
        return 0, len(audio)
    env = np.sqrt(np.mean(audio[:n*step].reshape(n, step)**2, axis=1))
    active = np.where(env > max(.001, float(env.max()) * .025))[0]
    if not len(active):
        return 0, len(audio)
    return (max(0, int(active[0]*step - .04*sr)),
            min(len(audio), int((active[-1]+1)*step + .08*sr)))


def _loudnorm(ffmpeg, source, destination, sr, channels, target_lufs, peak_db):
    """Two-pass loudnorm; return measured parameters. Short unmeasurable clips skip."""
    base = f'loudnorm=I={target_lufs}:TP={peak_db}:LRA=11'
    measured = subprocess.run([str(ffmpeg), '-hide_banner', '-nostats', '-i', str(source),
                               '-af', base + ':print_format=json', '-f', 'null', '-'],
                              capture_output=True, text=True, encoding='utf8', errors='replace')
    if measured.returncode:
        raise RuntimeError('loudnorm measurement failed: ' + measured.stderr[-3000:])
    begin, end = measured.stderr.rfind('{'), measured.stderr.rfind('}')
    if begin < 0 or end < begin:
        raise RuntimeError('loudnorm did not return measurement JSON')
    stats = json.loads(measured.stderr[begin:end+1])
    required = ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')
    if not all(math.isfinite(float(stats[k])) for k in required):
        return {**stats, 'skipped': 'Integrated LUFS unavailable for this short/quiet clip'}
    filters = (base + f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
               + f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
               + f":offset={stats['target_offset']}:linear=true:print_format=json")
    _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', source,
          '-af', filters, '-ar', str(sr), '-ac', str(channels), '-c:a', 'pcm_f32le', destination])
    return stats


def fit_rows(root, rows, out, mode='speedup', trim=True, event=None,
             loudness='original', target_lufs=-20.0, gain_db=0.0, peak_db=-1.0):
    """Fit raw/<id>.wav. Return reports; write fit-manifest.json.

    Every timing mode performs rate/channel conversion. Loudness: `original`
    matches original full-file RMS, `none` skips normalization, `lufs` uses
    measured two-pass FFmpeg loudnorm. Then user gain and sample peak safety
    cap apply in all modes. Clips too short for integrated LUFS fall back to
    original RMS and report a warning. `none` timing
    retains the (optionally boundary-trimmed) speech duration, with no pad/cut.
    Failure raises; previously completed rows remain available for a later run.
    """
    progress = event
    if mode not in ('speedup', 'both', 'pad', 'none'):
        raise ValueError(f'Unknown fit mode: {mode}')
    if loudness not in ('original', 'none', 'lufs'):
        raise ValueError(f'Unknown loudness mode: {loudness}')
    if not all(math.isfinite(v) for v in (target_lufs, gain_db, peak_db)):
        raise ValueError('Loudness parameters must be finite')
    if not -70 <= target_lufs <= -5 or not -9 <= peak_db <= 0 or not -60 <= gain_db <= 60:
        raise ValueError('Allowed ranges: target_lufs -70..-5, peak_db -9..0, gain_db -60..60')
    root, out, rows = Path(root).resolve(), Path(out).resolve(), _rows(rows)
    processed = out / 'processed'
    processed.mkdir(parents=True, exist_ok=True)
    reports = []
    ffmpeg = _ffmpeg(root)
    for index, row in enumerate(rows, 1):
        ident = str(row['id'])
        audio, sr = sf.read(out / 'raw' / (ident + '.wav'))
        audio = audio.mean(axis=1) if audio.ndim == 2 else audio
        if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .001:
            raise ValueError(f'{ident}: empty, silent or invalid raw speech')
        original, orig_sr = sf.read(_inside(root, row['original_wav']))
        frames = len(original)
        channels = 1 if original.ndim == 1 else original.shape[1]
        duration = frames / orig_sr
        start, end = _trim_bounds(audio, sr) if trim else (0, len(audio))
        audio = audio[start:end]
        ratio = len(audio) / sr / duration
        speed = max(1., ratio) if mode == 'speedup' else ratio if mode == 'both' else 1.
        if mode == 'pad' and len(audio) / sr > duration + 1 / orig_sr:
            raise ValueError(f'{ident}: pad mode cannot fit {len(audio)/sr:.3f}s '
                             f'into {duration:.3f}s without cutting speech')
        source = processed / (ident + '-trim.wav')
        fitted = processed / (ident + '-fitted.wav')
        sf.write(source, audio, sr, subtype='PCM_16')
        filters = []
        if abs(speed - 1.) > 1e-9:
            filters.append(f'rubberband=tempo={speed}:pitch=1:formant=preserved:pitchq=quality')
        if mode != 'none':
            filters += ['apad', f'atrim=duration={duration}']
        with tempfile.TemporaryDirectory(prefix='fit-', dir=processed) as temp:
            tempwav = Path(temp) / 'fitted.wav'
            command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', source]
            if filters:
                command += ['-af', ','.join(filters)]
            command += ['-ar', str(orig_sr), '-ac', str(channels), '-c:a', 'pcm_s16le', tempwav]
            _run(command)
            data, actual_sr = sf.read(tempwav)
            if actual_sr != orig_sr:
                raise RuntimeError(f'{ident}: incorrect sample rate')
            if mode != 'none':
                data = data[:frames]
                if len(data) < frames:
                    data = np.pad(data, [(0, frames-len(data))] + ([(0, 0)] if data.ndim == 2 else []))
            rms = float(np.sqrt(np.mean(data*data)))
            original_rms = float(np.sqrt(np.mean(original*original)))
            normalization_gain = original_rms / max(rms, 1e-8) if loudness == 'original' else 1.
            loudnorm_stats = None
            if loudness == 'lufs':
                sf.write(tempwav, data, orig_sr, subtype='FLOAT')
                normalized = Path(temp) / 'loudness.wav'
                loudnorm_stats = _loudnorm(ffmpeg, tempwav, normalized, orig_sr, channels,
                                          target_lufs, peak_db)
                if 'skipped' not in loudnorm_stats:
                    normalized_data, normalized_sr = sf.read(normalized)
                    if normalized_sr != orig_sr or normalized_data.shape != data.shape:
                        raise RuntimeError(f'{ident}: loudnorm changed frame count/rate/channels')
                    data = normalized_data
                    normalization_gain = float(np.sqrt(np.mean(data*data))) / max(rms, 1e-8)
                else:
                    normalization_gain = original_rms / max(rms, 1e-8)
                    data *= normalization_gain
                    loudnorm_stats['fallback'] = 'original'
                    _emit(progress, 'loudness_warning', id=ident, warning=loudnorm_stats['skipped'])
            else:
                data *= normalization_gain
            requested_gain = 10 ** (gain_db / 20)
            peak_limit = 10 ** (peak_db / 20)
            applied_gain = min(requested_gain, peak_limit / max(float(np.max(np.abs(data))), 1e-8))
            data *= applied_gain
            gain = normalization_gain * applied_gain
            if not np.isfinite(data).all() or np.max(np.abs(data)) <= .001:
                raise ValueError(f'{ident}: invalid fitted speech')
            sf.write(tempwav, data, orig_sr, subtype='PCM_16')
            os.replace(tempwav, fitted)
        report = dict(id=ident, speaker=row.get('speaker'), text=row.get('tts_ru'),
                      mode=mode, original_seconds=duration, fitted_seconds=len(data)/orig_sr,
                      speed=speed, requested_speed=ratio, trim_start=start, trim_end=end,
                      natural_speed_with_padding=mode in ('pad', 'speedup') and ratio < 1,
                      gain=gain, exact_original_frames=mode != 'none', trim=trim,
                      loudness=loudness, target_lufs=target_lufs, peak_db=peak_db,
                      requested_gain_db=gain_db, applied_gain_db=20*math.log10(applied_gain),
                      normalization_gain=normalization_gain,
                      effective_total_gain_db=20*math.log10(max(gain, 1e-20)),
                      peak_limited=applied_gain < requested_gain - 1e-12,
                      loudnorm_measurement=loudnorm_stats,
                      raw_sha256=_sha256(out / 'raw' / (ident + '.wav')),
                      fitted_sha256=_sha256(fitted),
                      original_sha256=_sha256(_inside(root, row['original_wav'])))
        reports.append(report)
        _json(out / 'fit-manifest.json', {'mode': mode, 'trim': trim, 'loudness': loudness,
              'target_lufs': target_lufs, 'gain_db': gain_db, 'peak_db': peak_db, 'rows': reports})
        _emit(progress, 'fit_line', current=index, total=len(rows), **report)
    return reports


def build_package(root, rows, out, package_name='NWTD_RU_Qwen_P.pak', event=None):
    """Build only selected ready rows, in a fresh isolated stage; verify every WEM.

    Variable lengths from fit mode `none` are allowed and reported. Never installs.
    Returns build manifest including absolute pak_path and SHA256.
    """
    progress = event
    root, out, rows = Path(root).resolve(), Path(out).resolve(), _rows(rows)
    if Path(package_name).name != package_name or not package_name.endswith('.pak'):
        raise ValueError('package_name must be a plain .pak filename')
    out.mkdir(parents=True, exist_ok=True)
    for field in ('media_path', 'bank_path'):
        values = [r[field].replace('\\', '/') for r in rows]
        if len(values) != len(set(values)):
            raise ValueError(f'Selected rows share {field}; merge patches explicitly before packaging')
    fit_path = out / 'fit-manifest.json'
    fits = {r['id']: r for r in json.loads(fit_path.read_text(encoding='utf8'))['rows']} if fit_path.exists() else {}
    report, expected = [], set()
    tools = root / 'work/tools'
    (root / 'work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='qwen-pack-', dir=root / 'work') as temp:
        stage = Path(temp) / 'stage'
        stage.mkdir()
        for index, row in enumerate(rows, 1):
            ident = str(row['id'])
            fitted = out / 'processed' / (ident + '-fitted.wav')
            fit = fits.get(ident)
            if not fit or fit.get('raw_sha256') != _sha256(out / 'raw' / (ident + '.wav')) or fit.get('fitted_sha256') != _sha256(fitted) or fit.get('original_sha256') != _sha256(_inside(root, row['original_wav'])):
                raise ValueError(f'{ident}: missing/stale fit metadata; run fit again')
            data, sr = sf.read(fitted)
            original = sf.info(_inside(root, row['original_wav']))
            channels = 1 if data.ndim == 1 else data.shape[1]
            if sr != original.samplerate or channels != original.channels:
                raise ValueError(f'{ident}: rate/channels differ from original; run fit first')
            if not np.isfinite(data).all() or not len(data):
                raise ValueError(f'{ident}: invalid fitted data')
            fit = fits.get(ident, {})
            if fit.get('exact_original_frames', True) and len(data) != original.frames:
                raise ValueError(f'{ident}: frame mismatch; variable duration requires fit mode none')
            media = _inside(stage, row['media_path'])
            bank = _inside(stage, row['bank_path'])
            media.parent.mkdir(parents=True, exist_ok=True)
            bank.parent.mkdir(parents=True, exist_ok=True)
            _run([sys.executable, tools / 'wwav.py', 'convert', fitted, media,
                  '--codec', 'pcm', '--layout', 'packed'])
            bank_data = bytearray(_inside(root / 'work/extracted', row['bank_path']).read_bytes())
            fields = list(ET.parse(_inside(root, row['bank_xml'])).iter('field'))
            plugins = [f for f in fields if f.attrib.get('name') == 'ulPluginID']
            sizes = [f for f in fields if f.attrib.get('name') == 'uInMemoryMediaSize']
            if len(plugins) != 1 or len(sizes) != 1:
                raise ValueError(f'{ident}: bank is not a supported single-media bank')
            plugin, size = plugins[0], sizes[0]
            if int(plugin.attrib['value'], 0) != 0x40001:
                raise ValueError(f'{ident}: expected Vorbis plugin 0x40001')
            plugin_offset, size_offset = int(plugin.attrib['offset']), int(size.attrib['offset'])
            if struct.unpack_from('<I', bank_data, plugin_offset)[0] != 0x40001:
                raise ValueError(f'{ident}: bank XML does not match bank bytes')
            struct.pack_into('<I', bank_data, plugin_offset, 0x10001)
            struct.pack_into('<I', bank_data, size_offset, media.stat().st_size)
            bank.write_bytes(bank_data)
            verified = out / 'processed' / (ident + '-verified.wav')
            _run([tools / 'vgmstream/vgmstream-cli.exe', '-o', verified, media])
            decoded, decoded_sr = sf.read(verified)
            if decoded_sr != sr or decoded.shape != data.shape or np.max(np.abs(decoded-data)) >= .0001:
                raise ValueError(f'{ident}: WEM roundtrip verification failed')
            expected.update([row['media_path'].replace('\\', '/'), row['bank_path'].replace('\\', '/')])
            entry = {**fit, 'id': ident, 'speaker': row.get('speaker'), 'text': row.get('tts_ru'),
                     'media_bytes': media.stat().st_size, 'fitted_seconds': len(data)/sr,
                     'original_seconds': original.duration, 'verified': True}
            report.append(entry)
            _emit(progress, 'pack_line', current=index, total=len(rows), **entry)
        temporary_pak = Path(temp) / package_name
        _run([tools / 'repak/repak.exe', 'pack', '--version', 'V11', stage, temporary_pak])
        listing = _run([tools / 'repak/repak.exe', 'list', temporary_pak]).splitlines()
        if set(listing) != expected or len(listing) != len(expected):
            raise ValueError('PAK entries do not exactly match selected bank/media paths')
        pak = out / package_name
        shutil.copy2(temporary_pak, out / (package_name + '.tmp'))
        os.replace(out / (package_name + '.tmp'), pak)
    manifest = dict(status='built; all media roundtrips verified; runtime listener review pending',
                    lines=len(rows), banks=len(rows), media=len(rows), pak_path=str(pak),
                    pak_bytes=pak.stat().st_size, pak_sha256=_sha256(pak), files=listing, timing=report)
    _json(out / 'build-manifest.json', manifest)
    _emit(progress, 'build_done', lines=len(rows), pak_path=str(pak), pak_sha256=manifest['pak_sha256'])
    return manifest


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_game_closed():
    if os.name != 'nt':
        raise RuntimeError('Installation process check supports Windows only')
    result = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   "@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'detnoir*' -or $_.ProcessName -like 'Nobody*Wants*Die*' }).Count"])
    if int(result.strip()) != 0:
        raise RuntimeError('Game is running; close it before installing a PAK')


def install_package(root, out, package_name='NWTD_RU_Qwen_P.pak', game_dir=None, event=None):
    """Explicit opt-in install: refuse running game, back up exact target, verify hash.

    Disables only fully covered known opening dub packages, after backup.
    Unknown or partially covered overlapping packages are refused.
    """
    progress = event
    if Path(package_name).name != package_name:
        raise ValueError('package_name must be a plain filename')
    root, package, game_dir = Path(root).resolve(), (Path(out) / package_name).resolve(), Path(game_dir).resolve()
    if not package.is_file() or package.suffix.lower() != '.pak':
        raise ValueError('A built .pak is required')
    paks = game_dir / 'detnoir/Content/Paks'
    if not paks.is_dir():
        raise FileNotFoundError(f'Game Paks folder not found: {paks}')
    _assert_game_closed()
    mods = paks / '~mods'
    mods.mkdir(exist_ok=True)
    target = mods / package.name
    repak = root / 'work/tools/repak/repak.exe'
    incoming = set(_run([repak, 'list', package]).splitlines())
    known_opening = {'NWTD_RU_Opening_Qwen_P.pak', 'NWTD_RU_Opening_P.pak'}
    covered = []
    for active in mods.glob('*.pak'):
        if active.name.lower() == target.name.lower():
            continue
        existing = set(_run([repak, 'list', active]).splitlines())
        overlap = incoming & existing
        if not overlap:
            continue
        if active.name in known_opening and existing <= incoming:
            covered.append(active)
            continue
        raise RuntimeError(f'Conflicting active PAK: {active}; {len(overlap)} overlapping entries. '
                           'Only fully covered known opening dub packages can be disabled automatically.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_dir = root / 'work/backups' / ('before-install-' + stamp)
    backup_dir.mkdir(parents=True)
    backup = backup_dir / target.name if target.exists() else None
    if backup:
        shutil.copy2(target, backup)
    for active in covered:
        shutil.copy2(active, backup_dir / active.name)
    expected = _sha256(package)
    temporary = target.with_suffix('.pak.tmp')
    disabled, replaced = [], False
    try:
        shutil.copy2(package, temporary)
        if _sha256(temporary) != expected:
            raise RuntimeError('Installation copy hash mismatch')
        _assert_game_closed()
        os.replace(temporary, target)
        replaced = True
        for active in covered:
            inactive = active.with_name(active.name + '.disabled.' + stamp)
            os.replace(active, inactive)
            disabled.append((active, inactive))
        if _sha256(target) != expected:
            raise RuntimeError('Installed PAK hash mismatch')
    except Exception:
        for active, inactive in reversed(disabled):
            os.replace(inactive, active)
        if replaced:
            if backup:
                shutil.copy2(backup, target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    result = dict(installed_path=str(target), sha256=expected, backup_path=str(backup) if backup else None, backup_dir=str(backup_dir),
                  disabled_packages=[str(inactive) for _, inactive in disabled])
    _json(package.parent / 'install-manifest.json', result)
    _emit(progress, 'installed', **result)
    return result


def make_preview(root, rows, out, filename='opening-preview.wav', gap_seconds=.1,
                 sample_rate=48000, event=None):
    """Concatenate fitted rows in manifest order, streaming output; return timeline."""
    from scipy.signal import resample_poly
    progress = event
    rows, out = _rows(rows), Path(out).resolve()
    if Path(filename).name != filename or gap_seconds < 0:
        raise ValueError('Invalid preview filename/gap')
    destination = out / filename
    timeline, position = [], 0
    gap = np.zeros(round(sample_rate*gap_seconds))
    with sf.SoundFile(destination, 'w', samplerate=sample_rate, channels=1, subtype='PCM_16') as stream:
        for index, row in enumerate(rows, 1):
            audio, sr = sf.read(out / 'processed' / (str(row['id']) + '-fitted.wav'))
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            if sr != sample_rate:
                divisor = math.gcd(sr, sample_rate)
                audio = resample_poly(audio, sample_rate//divisor, sr//divisor)
            timeline.append(dict(id=row['id'], speaker=row.get('speaker'), text=row.get('tts_ru'),
                                 start=position/sample_rate, seconds=len(audio)/sample_rate))
            stream.write(audio)
            stream.write(gap)
            position += len(audio) + len(gap)
            _emit(progress, 'preview_line', current=index, total=len(rows), id=row['id'])
    _json(out / (Path(filename).stem + '-timeline.json'), timeline)
    _emit(progress, 'preview_done', path=str(destination), seconds=position/sample_rate)
    return timeline


# Short alias for pipeline callers.
preview = make_preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['fit', 'build', 'preview', 'install'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['speedup', 'both', 'pad', 'none'], default='speedup')
    parser.add_argument('--no-trim', action='store_true')
    parser.add_argument('--loudness', choices=['original', 'none', 'lufs'], default='original')
    parser.add_argument('--target-lufs', type=float, default=-20.)
    parser.add_argument('--gain-db', type=float, default=0.)
    parser.add_argument('--peak-db', type=float, default=-1.)
    parser.add_argument('--package-name', default='NWTD_RU_Qwen_P.pak')
    parser.add_argument('--game-dir', type=Path, help='Explicit game install, required for install')
    args = parser.parse_args()
    if args.action == 'install' and args.game_dir is None:
        parser.error('--game-dir is required for installation')
    args.out = args.out if args.out.is_absolute() else args.root / args.out
    progress = lambda event, **fields: print(json.dumps({'event': event, **fields}, ensure_ascii=True), flush=True)
    if args.action == 'install':
        install_package(args.root, args.out, args.package_name, args.game_dir, event=progress)
        return
    manifest = args.manifest or args.root / 'work/opening-ready.json'
    if not manifest.is_absolute():
        manifest = args.root / manifest
    rows = json.loads(manifest.read_text(encoding='utf8'))
    if args.action == 'fit':
        fit_rows(args.root, rows, args.out, args.mode, not args.no_trim, event=progress,
                 loudness=args.loudness, target_lufs=args.target_lufs,
                 gain_db=args.gain_db, peak_db=args.peak_db)
    elif args.action == 'build':
        build_package(args.root, rows, args.out, args.package_name, event=progress)
    else:
        make_preview(args.root, rows, args.out, event=progress)


if __name__ == '__main__':
    main()
