"""Create a dedicated environment without changing the host interpreter."""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import venv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--venv', default='.venv')
    p.add_argument('--extra', choices=['qwen'])
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--pip-timeout', type=int, default=15)
    p.add_argument('--pip-retries', type=int, default=1)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = (root / a.venv).resolve()
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    spec = str(root) + ('[' + a.extra + ']' if a.extra else '')
    if a.pip_timeout < 1 or a.pip_retries < 0:
        p.error('pip-timeout must be positive and pip-retries nonnegative')
    cmd = [str(python), '-m', 'pip', 'install', '--timeout', str(a.pip_timeout),
           '--retries', str(a.pip_retries), '-e', spec]
    print({'environment': str(env), 'install': cmd})
    if not a.dry_run:
        if env.exists():
            p.error('Environment already exists; use its Python to install explicitly')
        venv.create(env, with_pip=True)
        subprocess.run(cmd, check=True)


if __name__ == '__main__':
    main()
