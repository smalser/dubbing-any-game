"""Build exact Articy text/speaker/SoundEffect GUID joins; no fuzzy matching."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

def unwrap(value):
    return value['value']['mValue']

def read_rows(source):
    with source.open(encoding='utf-8') as stream:
        yield from stream

def join_objects(source: Path, output: Path):
    if output.exists():
        raise ValueError('Mapping output must be a new directory')
    objects, locales, manager = {}, {}, None
    for raw in read_rows(source):
        row = json.loads(raw)
        data = row['data']
        if row['class'] == 'ArticyLocalizationPackage':
            keys, values = data['mLocalizedStringsKeys'], data['mLocalizedStringsValues']
            if len(keys) != len(values) or len(set(keys)) != len(keys):
                raise ValueError('Ambiguous localization keys: ' + data['m_Name'])
            language = int(data['m_Name'].rsplit('_', 1)[1])
            if language in locales:
                raise ValueError('Duplicate localization package for language ' + str(language))
            locales[language] = {'values': dict(zip(keys, values)), 'path_id': row['path_id']}
        elif row['class'] == 'ArticyLocalizationManager':
            if manager is not None:
                raise ValueError('Duplicate ArticyLocalizationManager')
            manager = data
        elif 'id' in data:
            if data['id'] in objects:
                raise ValueError('Duplicate Articy object ID: ' + str(data['id']))
            objects[data['id']] = row
    if manager is None:
        raise ValueError('Missing ArticyLocalizationManager evidence')
    languages = {v['mCultureName']: v['mArticyLanguageId'] for v in manager['mLanguages']}
    ru_id, en_id, base_id = languages['ru'], languages['en-GB'], languages['en-SR']
    def local(key, language):
        return locales.get(language, {}).get('values', {}).get(key)
    def ancestry(data):
        result, seen, parent = [], set(), data.get('parentId')
        while parent in objects and parent not in seen:
            seen.add(parent)
            item = objects[parent]
            parent_data = item['data']
            key = unwrap(parent_data['mDisplayName']) if 'mDisplayName' in parent_data else ''
            result.append({'id': str(parent), 'class': item['class'], 'path_id': item['path_id'],
                           'name': local(key, base_id) or parent_data.get('technicalName', '')})
            parent = parent_data.get('parentId')
        return result
    ready, unresolved = [], []
    for ident, obj in objects.items():
        if obj['class'] != 'InteractableDialogueFragment':
            continue
        data = obj['data']
        key = unwrap(data['mText'])
        template = data['mTemplate']['value']
        trigger = template['mSoundEffectTriggerFeatures']['value']
        sound_id = trigger['mSoundEffect']['id']
        if not sound_id:
            unresolved.append({'id': str(ident), 'reason': 'no_sound_effect', 'text_key': key})
            continue
        speaker_id = data['mSpeaker']['id']
        speaker, sound = objects.get(speaker_id), objects.get(sound_id)
        if not speaker or speaker['class'] not in {'Character', 'MainCharacter'} or not sound or sound['class'] != 'SoundEffect':
            unresolved.append({'id': str(ident), 'reason': 'missing_speaker_or_sound', 'text_key': key})
            continue
        feature = sound['data']['mTemplate']['value']['mSoundEffectFeature']['value']
        guid = unwrap(feature['mFmodId'])
        ru, en = local(key, ru_id), local(key, en_id) or local(key, base_id)
        if not ru or not en or not re.fullmatch(r'\{[0-9a-fA-F-]{36}\}', guid) or feature['mSoundEffectType'] != 1:
            unresolved.append({'id': str(ident), 'reason': 'missing_text_or_not_voiceover', 'text_key': key})
            continue
        speaker_key = unwrap(speaker['data']['mDisplayName'])
        ready.append({'id': str(ident), 'technical_name': data['technicalName'],
                      'speaker_id': str(speaker_id), 'speaker': local(speaker_key, base_id),
                      'speaker_ru': local(speaker_key, ru_id), 'text_ru': ru, 'text_en': en,
                      'event_guid': guid, 'event_name': unwrap(feature['mFmodName']),
                      'sound_id': str(sound_id), 'story': ancestry(data),
                      'evidence': {'source': 'resources.assets', 'fragment_path_id': obj['path_id'],
                                   'speaker_path_id': speaker['path_id'], 'sound_path_id': sound['path_id'],
                                   'text_key': key, 'speaker_key': speaker_key,
                                   'ru_language_id': ru_id, 'en_language_id': en_id,
                                   'ru_package_path_id': locales[ru_id]['path_id'],
                                   'en_package_path_id': locales[en_id]['path_id']}})
    output.mkdir(parents=True, exist_ok=False)
    (output / 'mapping.json').write_text(json.dumps({'entries': ready}, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'unresolved.json').write_text(json.dumps(unresolved, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'mapped': len(ready), 'unresolved': len(unresolved),
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'audio_extracted': False, 'in_game_verified': False}
    (output / 'coverage.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    with (output / 'coverage.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, ['id', 'speaker', 'event_guid', 'event_name', 'text_key'])
        writer.writeheader()
        for row in ready:
            writer.writerow({**{k: row[k] for k in ['id', 'speaker', 'event_guid', 'event_name']}, 'text_key': row['evidence']['text_key']})
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if args.dry_run:
            print(json.dumps({'read': str(args.objects), 'write': str(args.output), 'fuzzy_matching': False}))
        else:
            from ..universal_modder import require_toolkit
            require_toolkit()
            print(json.dumps(join_objects(args.objects.resolve(), args.output.resolve())))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, 'Mapping failed: ' + str(exc) + '\n')

if __name__ == '__main__':
    main()
