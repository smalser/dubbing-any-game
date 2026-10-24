"""Export verified speech and exact Articy event IDs for the Unity/FMOD runtime."""
import argparse
from pathlib import Path
import re
import shutil
import uuid

from ...audio import audio
from ...storage import digest, read, write
from ..universal_modder import require_toolkit


def plan(manifest, selection, generated, output):
    if output.exists():
        raise ValueError('Runtime export must use a new output directory')
    source, chosen = read(manifest), read(selection)
    receipt = read(generated / 'verification.json')
    if receipt.get('test_tones') is not False or receipt.get('manifest_sha256') != digest(manifest):
        raise ValueError('Expected verified real speech for the exact prepared manifest')
    lines = source['lines']
    rows = {r['id']: r for r in lines}
    selected = {r['id']: r for r in chosen['entries']}
    files = {r['id']: r for r in receipt['files']}
    if len(rows) != len(lines) or len(selected) != len(chosen['entries']) or len(files) != len(receipt['files']):
        raise ValueError('Duplicate input IDs')
    if set(rows) != set(selected) or set(rows) != set(files) or receipt['count'] != len(rows):
        raise ValueError('Prepared, selected and verified IDs must match exactly')
    events, entries = set(), []
    for row in lines:
        ident = row['id']
        if not re.fullmatch(r'[0-9]+', ident):
            raise ValueError('Expected decimal Articy ID')
        exact = selected[ident]
        event = str(uuid.UUID(row['event_guid'].strip('{}')))
        if event != str(uuid.UUID(exact['event_guid'].strip('{}'))) or event in events:
            raise ValueError('Conflicting or duplicate event mapping: ' + ident)
        events.add(event)
        if row['speaker'] != exact['speaker_id'] or row['reference_speaker_id'] != row['speaker']:
            raise ValueError('Speaker/reference identity mismatch: ' + ident)
        if not re.fullmatch(r'[0-9]+', exact['sound_id']):
            raise ValueError('Expected exact Articy sound object ID')
        wav = generated / 'fitted' / (ident + '.wav')
        if digest(wav) != files[ident]['sha256']:
            raise ValueError('Verified WAV changed: ' + ident)
        samples, rate = audio(wav)
        fmt = row['format']
        if (rate, samples.shape[1], len(samples)) != (fmt['sample_rate'], fmt['channels'], fmt['frames']):
            raise ValueError('Event timeline WAV format mismatch: ' + ident)
        entries.append({'id': ident, 'event_guid': event, 'sound_id': exact['sound_id'],
                        'wav': 'audio/' + ident + '.wav', 'sha256': files[ident]['sha256']})
    return {'schema_version': 1, 'voice_bus': 'bus:/Voice', 'entries': entries,
            'coverage': 'selected_pilot_only', 'in_game_verified': False,
            'perceptual_qa': 'pending', 'source_manifest_sha256': digest(manifest),
            'selection_sha256': digest(selection), 'verification_sha256': digest(generated / 'verification.json')}


def export(manifest, selection, generated, output):
    result = plan(manifest, selection, generated, output)
    (output / 'audio').mkdir(parents=True)
    for entry in result['entries']:
        source = generated / 'fitted' / (entry['id'] + '.wav')
        destination = output / entry['wav']
        shutil.copyfile(source, destination)
        if digest(destination) != entry['sha256']:
            raise ValueError('Exported WAV hash mismatch')
    write(output / 'manifest.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'selection', 'generated', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if not args.dry_run:
            require_toolkit()
        operation = plan if args.dry_run else export
        result = operation(args.manifest.resolve(), args.selection.resolve(), args.generated.resolve(), args.output.resolve())
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
