"""Explicit, opt-in model download; never called by synthesis automatically."""
import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, help='Model repository identifier')
    p.add_argument('--revision', required=True, help='Pinned commit for reproducible downloads')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    print({'repo': a.repo, 'revision': a.revision, 'output': str(a.output.resolve())})
    if not a.dry_run:
        from huggingface_hub import snapshot_download
        snapshot_download(a.repo, revision=a.revision, local_dir=str(a.output))


if __name__ == '__main__':
    main()
