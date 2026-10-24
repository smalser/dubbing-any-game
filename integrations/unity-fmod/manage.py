"""Stage/install/uninstall exact FMOD overrides. All mutations require --apply."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_receipt(path, receipt):
    temporary = path.with_name(path.name + '.ud-new-' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def inside(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe relative path: ' + str(relative))
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Path escapes root')
    return target


def validate_manifest(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema_version') != 1 or not data.get('entries'):
        raise ValueError('Expected schema_version=1 and nonempty entries')
    if not isinstance(data.get('voice_bus', 'bus:/Voice'), str) or not data.get('voice_bus', 'bus:/Voice').startswith('bus:/'):
        raise ValueError('Expected exact FMOD bus:/ path')
    ids, events, audio_paths = set(), set(), set()
    for entry in data['entries']:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', entry['id']) or entry['id'].endswith('.'):
            raise ValueError('ID must be a safe portable basename')
        if entry['id'].split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(n) for n in range(1, 10)), *('LPT'+str(n) for n in range(1, 10))}:
            raise ValueError('Reserved portable ID')
        event = str(uuid.UUID(entry['event_guid']))
        if event in events or entry['id'].casefold() in ids:
            raise ValueError('Duplicate event or ID')
        ids.add(entry['id'].casefold()); events.add(event)
        audio = inside(path.parent, entry['wav'])
        canonical = str(audio).casefold()
        if canonical in audio_paths:
            raise ValueError('Conflicting duplicate WAV path')
        audio_paths.add(canonical)
        if digest(audio) != entry['sha256']:
            raise ValueError('WAV hash mismatch: ' + entry['id'])
        with wave.open(str(audio), 'rb') as wav:
            if wav.getnframes() <= 0 or wav.getnchannels() not in (1, 2) or wav.getsampwidth() != 2:
                raise ValueError('Expected nonempty 16-bit mono/stereo PCM WAV')
        entry['event_guid'] = event
    return data


def closed_game(game, game_exe):
    if Path(game_exe).name != game_exe or not game_exe.lower().endswith('.exe'):
        raise ValueError('--game-exe must be an explicit relative executable filename')
    exe = inside(game, game_exe)
    if not exe.is_file():
        raise ValueError('Game executable not found')
    script = "$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq '" + str(exe).replace("'", "''") + "'} | Select-Object -ExpandProperty ProcessId"
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, check=True)
    if result.stdout.strip():
        raise ValueError('Game is running, PID ' + result.stdout.strip())


def install_plan(game, stage, loader):
    manifest = validate_manifest(stage / 'manifest.json')
    files = {}
    allowed = [Path('manifest.json'), Path('UniversalDubbing.Fmod.dll')] + [Path(e['wav']) for e in manifest['entries']]
    for rel in allowed:
        source = inside(stage, rel)
        if not source.is_file():
            raise ValueError('Missing stage file: ' + str(source))
        files[Path('BepInEx/plugins/UniversalDubbing') / rel] = source
    if loader:
        for source in loader.rglob('*'):
            if not source.is_file():
                continue
            rel = source.relative_to(loader)
            if (rel.parts[0] == 'BepInEx' and len(rel.parts) >= 3 and rel.parts[1] == 'core') or str(rel) in ('winhttp.dll', 'doorstop_config.ini', '.doorstop_version'):
                target = inside(game, rel)
                if target.exists() and digest(target) != digest(source):
                    raise ValueError('Conflicting existing loader file, refusing overwrite: ' + str(rel))
                files[rel] = source
    return files


def install(args):
    game, stage = Path(args.game).resolve(), Path(args.stage).resolve()
    closed_game(game, args.game_exe)
    files = install_plan(game, stage, Path(args.loader_root).resolve() if args.loader_root else None)
    changes = [(rel, src) for rel, src in files.items() if not inside(game, rel).exists() or digest(inside(game, rel)) != digest(src)]
    print(json.dumps({'action': 'install', 'apply': args.apply, 'files': [str(r) for r, _ in changes]}, indent=2))
    if not args.apply:
        return
    receipt_path = Path(args.receipt).resolve()
    if receipt_path.exists():
        raise ValueError('Receipt must be a new path')
    backup = receipt_path.parent / (receipt_path.stem + '-backup-' + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    receipt = {'schema_version': 1, 'game': str(game), 'game_exe': args.game_exe, 'created_utc': datetime.now(timezone.utc).isoformat(), 'state': 'installing', 'files': []}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    for rel, src in changes:
        target = inside(game, rel)
        old = None
        if target.exists():
            old = inside(backup, rel); old.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(target, old)
        item = {'path': str(rel), 'sha256': digest(src), 'backup': str(old) if old else None, 'previous_sha256': digest(old) if old else None, 'state': 'pending'}
        receipt['files'].append(item)
        write_receipt(receipt_path, receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.ud-new-' + uuid.uuid4().hex)
        try:
            shutil.copy2(src, temp)
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
        if digest(target) != item['sha256']:
            raise ValueError('Installed hash mismatch')
        item['state'] = 'applied'
        write_receipt(receipt_path, receipt)
    receipt['state'] = 'installed'
    write_receipt(receipt_path, receipt)


def uninstall(args):
    path = Path(args.receipt)
    receipt = json.loads(path.read_text(encoding='utf-8'))
    game = Path(receipt['game']).resolve(); closed_game(game, receipt['game_exe'])
    recovering = receipt.get('state') in {'uninstalling', 'uninstalled'}
    for item in receipt['files']:
        target = inside(game, item['path'])
        current = digest(target) if target.exists() else None
        previous_allowed = recovering or (receipt.get('state') == 'installing' and item.get('state') == 'pending')
        allowed = {item['sha256'], None}
        if previous_allowed:
            allowed.add(item['previous_sha256'])
        if current not in allowed:
            raise ValueError('Installed file changed; preserve it for manual review: ' + str(target))
        if item['backup'] and digest(item['backup']) != item['previous_sha256']:
            raise ValueError('Backup hash mismatch')
    print(json.dumps({'action': 'uninstall', 'apply': args.apply, 'files': len(receipt['files'])}))
    if args.apply:
        receipt['state'] = 'uninstalling'
        write_receipt(path, receipt)
        for item in reversed(receipt['files']):
            target = inside(game, item['path'])
            if item['backup']:
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + '.ud-restore-' + uuid.uuid4().hex)
                try:
                    shutil.copy2(item['backup'], temp)
                    if digest(temp) != item['previous_sha256']:
                        raise ValueError('Restored hash mismatch')
                    temp.replace(target)
                finally:
                    if temp.exists():
                        temp.unlink()
            elif target.exists():
                target.unlink()
            item['state'] = 'restored'
            write_receipt(path, receipt)
        receipt['state'] = 'uninstalled'
        write_receipt(path, receipt)


def stage(args):
    manifest = Path(args.manifest).resolve(); data = validate_manifest(manifest)
    if args.integration_config:
        integration = json.loads(Path(args.integration_config).read_text(encoding='utf-8-sig'))
        if integration.get('schema_version') != 1 or not integration.get('voice_bus', '').startswith('bus:/'):
            raise ValueError('Invalid integration config voice_bus')
        data['voice_bus'] = integration['voice_bus']
    destination = Path(args.output).resolve()
    print(json.dumps({'action': 'stage', 'apply': args.apply, 'entries': len(data['entries']), 'output': str(destination)}))
    if args.apply:
        if destination.exists():
            raise ValueError('Stage must be a new directory')
        destination.mkdir(parents=True)
        for entry in data['entries']:
            original = inside(manifest.parent, entry['wav'])
            entry['wav'] = 'audio/' + entry['id'] + '.wav'
            target = inside(destination, entry['wav']); target.parent.mkdir(exist_ok=True)
            shutil.copy2(original, target)
        shutil.copy2(args.plugin, destination / 'UniversalDubbing.Fmod.dll')
        (destination / 'manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        validate_manifest(destination / 'manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('stage'); p.add_argument('--manifest', required=True); p.add_argument('--plugin', required=True); p.add_argument('--output', required=True); p.add_argument('--integration-config')
    p = sub.add_parser('install'); p.add_argument('--game', required=True); p.add_argument('--game-exe', required=True); p.add_argument('--stage', required=True); p.add_argument('--loader-root'); p.add_argument('--receipt', required=True)
    p = sub.add_parser('uninstall'); p.add_argument('--receipt', required=True)
    for p in sub.choices.values():
        p.add_argument('--apply', action='store_true', help='Mutate files; default only prints a plan')
    args = parser.parse_args()
    try:
        globals()[args.command](args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
