"""Bounded offline Studio event renderer using the game's FMOD 2.02 ABI.

Enums verified against the installed FMODUnity bindings. NRT/stream update policy:
https://www.fmod.com/docs/2.02/api/core-api-system.html
No library or bank is copied or redistributed.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import uuid


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def render(native, banks, guid, output, max_seconds=60):
    """Render one event to float WAV, with a strict update budget."""
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError(f'Output already exists: {output}')
    if not 0 < max_seconds <= 120:
        raise ValueError('max-seconds must be within (0, 120]')
    uuid.UUID(guid.strip('{}'))
    if not banks or not all(path.is_file() for path in (native, *banks)):
        raise ValueError('Native library and at least one source bank must exist')
    dll = C.CDLL(str(native.resolve()))
    def call(name, *args):
        result = getattr(dll, name)(*args)
        if result:
            raise RuntimeError(f'{name}: FMOD result {result}')
    studio, core, event, instance = (C.c_void_p() for _ in range(4))
    # Header version in the game's FMOD.Factory binding: 131588 = 2.02.04.
    call('FMOD_Studio_System_Create', C.byref(studio), C.c_uint(131588))
    try:
        call('FMOD_Studio_System_GetCoreSystem', studio, C.byref(core))
        call('FMOD5_System_SetOutput', core, 5)  # WAVWRITER_NRT
        call('FMOD5_System_SetSoftwareFormat', core, 48000, 3, 0)  # STEREO
        call('FMOD5_System_SetDSPBufferSize', core, 512, 4)
        output.parent.mkdir(parents=True, exist_ok=True)
        filename = C.create_string_buffer(str(output.resolve()).encode('utf-8'))
        # SYNCHRONOUS_UPDATE | LOAD_FROM_UPDATE, STREAM_FROM_UPDATE
        call('FMOD_Studio_System_Initialize', studio, 64, 20, 1, C.cast(filename, C.c_void_p))
        sources = []
        for bank in banks:
            handle = C.c_void_p()
            call('FMOD_Studio_System_LoadBankFile', studio, str(bank.resolve()).encode('utf-8'), 0, C.byref(handle))
            sources.append({'path': str(bank.resolve()), 'sha256': sha256(bank)})
        uid = C.create_string_buffer(uuid.UUID(guid.strip('{}')).bytes_le, 16)
        call('FMOD_Studio_System_GetEventByID', studio, uid, C.byref(event))
        call('FMOD_Studio_EventDescription_LoadSampleData', event)
        call('FMOD_Studio_System_FlushSampleLoading', studio)
        length = C.c_int()
        call('FMOD_Studio_EventDescription_GetLength', event, C.byref(length))
        if length.value <= 0 or length.value > max_seconds * 1000:
            raise ValueError(f'Event length {length.value}ms exceeds finite render budget')
        call('FMOD_Studio_EventDescription_CreateInstance', event, C.byref(instance))
        call('FMOD_Studio_EventInstance_Start', instance)
        # Fixed duration includes a bounded DSP tail; Studio update drives NRT core.
        updates = int((length.value / 1000 + 0.3) * 48000 / 512) + 1
        for _ in range(updates):
            call('FMOD_Studio_System_Update', studio)
        state = C.c_int()
        call('FMOD_Studio_EventInstance_GetPlaybackState', instance, C.byref(state))
        call('FMOD_Studio_EventInstance_Stop', instance, 1)
    finally:
        call('FMOD_Studio_System_Release', studio)
    import soundfile as sf
    import numpy as np
    data, rate = sf.read(output, always_2d=True)
    if not data.size or not np.isfinite(data).all() or not np.any(data):
        raise ValueError('Rendered WAV is empty, silent or nonfinite')
    if state.value != 2:  # FMOD.Studio.PLAYBACK_STATE.STOPPED
        raise ValueError(f'Event did not finish within its duration plus tail: playback_state={state.value}')
    audible = np.flatnonzero(np.max(np.abs(data), axis=1) > 1e-5)
    metadata = {'event_guid': guid, 'native_library': str(native.resolve()),
                'native_sha256': sha256(native), 'source_banks': sources,
                'sample_rate': rate, 'channels': data.shape[1], 'frames': len(data),
                'event_length_ms': length.value, 'peak': float(np.max(np.abs(data))),
                'playback_state_at_end': state.value,
                'signal_threshold': 1e-5,
                'first_signal_frame': int(audible[0]) if audible.size else None,
                'last_signal_frame': int(audible[-1]) if audible.size else None,
                'timing_note': 'Writer includes DSP latency and tail; use event_length_ms for dialogue timing, not rendered frame count.',
                'sha256': sha256(output), 'method': 'FMOD Studio WAVWRITER_NRT event render'}
    output.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--bank', type=Path, action='append', required=True)
    parser.add_argument('--guid', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=60)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        uuid.UUID(args.guid.strip('{}'))
        for path in [args.native, *args.bank]:
            if not path.is_file():
                raise ValueError(f'Missing source: {path}')
        if args.output.exists() or args.output.with_suffix('.json').exists():
            raise ValueError(f'Output already exists: {args.output}')
        if not 0 < args.max_seconds <= 120:
            raise ValueError('max-seconds must be within (0, 120]')
        if args.dry_run:
            print(json.dumps({'event_guid': args.guid, 'output': str(args.output), 'banks': list(map(str, args.bank))}))
        else:
            from ..universal_modder import require_toolkit
            require_toolkit()
            print(json.dumps(render(args.native, args.bank, args.guid, args.output, args.max_seconds)))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'FMOD render failed: {exc}\n')


if __name__ == '__main__':
    main()
