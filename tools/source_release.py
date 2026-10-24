"""Build source ZIP from an allowlist, excluding game assets, caches and models."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path('dist/universal-dubbing-source.zip'))
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = []
    allowed_dirs = {'dubbing', 'docs', 'tools', 'tests', '.github', 'schemas'}
    allowed_root = {'dub.py', 'README.md', 'AGENTS.md', 'CLAUDE.md', 'LICENSE', 'THIRD_PARTY.md', 'pyproject.toml', '.gitignore'}
    examples = {'examples/demo/manifest.json', 'examples/demo/config.json', 'examples/comparison/index.html', 'examples/comparison/provenance.json'}
    for f in sorted(root.rglob('*')):
        if not f.is_file() or f.is_symlink():
            continue
        rel = f.relative_to(root)
        if '__pycache__' in rel.parts or f.suffix == '.pyc':
            continue
        if (len(rel.parts) == 1 and f.name in allowed_root) or rel.parts[0] in allowed_dirs or rel.as_posix() in examples:
            files.append((f, rel.as_posix()))
    print(json.dumps({'files': [r for _, r in files], 'output': str(a.output)}, indent=2))
    if a.dry_run:
        return
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(a.output, 'w', zipfile.ZIP_DEFLATED) as z:
        for f, rel in files:
            z.write(f, rel)
    checksum = hashlib.sha256(a.output.read_bytes()).hexdigest()
    a.output.with_suffix('.sha256').write_text(checksum + '  ' + a.output.name + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
