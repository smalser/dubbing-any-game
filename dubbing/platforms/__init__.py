"""Host-specific diagnostics only. No hardcoded game processes or install paths."""
import platform
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys


def diagnose(args):
    """Read-only readiness checks. Does not load weights, synthesize or download."""
    checks = []

    def check(name, passed, detail):
        checks.append({'check': name, 'passed': bool(passed), 'detail': detail})

    for package in ['numpy', 'soundfile'] + (['qwen-tts', 'torch', 'transformers'] if args.adapter == 'qwen' else []):
        try:
            version = importlib.metadata.version(package)
            check('package:' + package, True, version)
        except importlib.metadata.PackageNotFoundError:
            check('package:' + package, False, 'missing; install project dependencies / adapter extra')
    executable = shutil.which(args.ffmpeg)
    check('ffmpeg', executable is not None, executable or 'not found')
    if executable:
        try:
            result = subprocess.run([executable, '-hide_banner', '-filters'], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=10)
            check('ffmpeg:filters', result.returncode == 0, 'filter query')
            if args.timing == 'speedup':
                check('ffmpeg:rubberband', 'rubberband' in result.stdout, 'required only when tempo > 1')
        except (OSError, subprocess.TimeoutExpired) as exc:
            check('ffmpeg:filters', False, str(exc))
    if args.adapter == 'qwen':
        model = Path(args.model)
        present = model.is_dir() and (model / 'config.json').is_file() and any(model.rglob('*.safetensors'))
        check('model:local_files', present, 'config.json and safetensors present; compatibility is not validated')
        if all(c['passed'] for c in checks if c['check'] == 'package:torch'):
            try:
                import torch
                device = torch.device(args.device)
                available = device.type == 'cpu'
                if device.type == 'cuda':
                    available = torch.cuda.is_available() and (device.index or 0) < torch.cuda.device_count()
                elif device.type == 'mps':
                    available = torch.backends.mps.is_available()
                check('device:available', available, str(device) + '; availability does not prove adapter compatibility')
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                check('device:available', False, str(exc))
    elif args.adapter != 'mock':
        check('adapter:custom', False, 'custom adapter requires its own preflight; doctor does not execute it')
    try:
        from ..manifest import load_manifest
        from ..audio import audio
        rows = load_manifest(args)
        for path in {r['reference'] for r in rows}:
            audio(path)
        check('manifest:references', True, f'{len(rows)} selected lines; finite nonsilent reference WAVs')
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        check('manifest:references', False, str(exc))
    return {'os': platform.system(), 'architecture': platform.machine(), 'python': sys.version,
            'adapter': args.adapter, 'checks': checks,
            'ready_for_requested_checks': all(c['passed'] for c in checks),
            'model_loaded': False, 'speech_quality_verified': False}
