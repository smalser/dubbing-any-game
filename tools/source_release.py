"""Build a deterministic source ZIP from a reviewed, explicit file inventory."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


def source_files(root):
    """Never walk work, models, environments or unrestricted source directories."""
    inventory = root / 'tools' / 'source-files.txt'
    names = [s.strip() for s in inventory.read_text(encoding='utf-8').splitlines()
             if s.strip() and not s.lstrip().startswith('#')]
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError('Duplicate source inventory entries')
    files = []
    for name in sorted(names):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe source inventory path: ' + name)
        path = root.joinpath(*relative.parts)
        if any(p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)):
            raise ValueError('Symlinks are not allowed in source release: ' + name)
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Missing or escaping source file: ' + name)
        files.append((path, name))
    return files


def build(root, output):
    files = source_files(root)
    output = output.resolve()
    if output.suffix.lower() != '.zip':
        raise ValueError('Source release output must have a .zip suffix')
    checksum_file = output.with_suffix('.sha256')
    inputs = {p.resolve() for p, _ in files}
    if output in inputs or checksum_file in inputs:
        raise ValueError('Release output must not overwrite a source file')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.zip', delete=False) as f:
        temp = Path(f.name)
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, name in files:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        checksum = hashlib.sha256(temp.read_bytes()).hexdigest()
        os.replace(temp, output)
        checksum_file.write_text(checksum + '  ' + output.name + '\n', encoding='utf-8')
        return checksum
    finally:
        temp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path('dist/universal-dubbing-source.zip'))
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        files = source_files(root)
        print(json.dumps({'files': [name for _, name in files], 'output': str(args.output)}, indent=2))
        if not args.dry_run:
            print(json.dumps({'sha256': build(root, args.output)}))
    except (OSError, ValueError) as exc:
        p.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
