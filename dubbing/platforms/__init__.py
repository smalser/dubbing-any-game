"""Host-specific diagnostics only. No hardcoded game processes or install paths."""
import platform
import shutil
import sys


def diagnose(ffmpeg):
    return {'os': platform.system(), 'architecture': platform.machine(),
            'python': sys.version, 'ffmpeg': shutil.which(ffmpeg)}
