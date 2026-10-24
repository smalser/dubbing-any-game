"""Prepare exact NPC speech against a corrected FMOD event timeline render."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import wave

SOURCE = 'FMOD event timeline render'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def spoken_text(text):
    # ArticyUtils.GetDialogueTextWithContext uses § as speech/context delimiter.
    return ' '.join(re.sub(r'<[^>]*>', '', text.split('§', 1)[0]).split())

def plan(selection, originals, output, render_latency_frames=0, target='event'):
    if target != 'event' or type(render_latency_frames) is not int or render_latency_frames < 0:
        raise ValueError('Expected --target event and nonnegative integer latency frames')
    entries = json.loads(selection.read_text(encoding='utf-8'))['entries']
    ids = [r['id'] for r in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate selected IDs')
    corrected = output.parent / 'corrected-originals'
    if output.exists() or corrected.exists():
        raise FileExistsError('Refusing to overwrite manifest or corrected-originals: ' + str(output.parent))
    rows = []
    for row in entries:
        if row['speaker'] in {'You', 'Narrator', 'You Subtext'}:
            raise ValueError('Player/narrator voice is excluded from this NPC pilot')
        name = row['event_name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Unsafe event name')
        raw = (originals / (name + '.wav')).resolve()
        metadata = json.loads((originals / (name + '.json')).read_text(encoding='utf-8'))
        if metadata.get('method') != 'FMOD Studio WAVWRITER_NRT event render':
            raise ValueError('Expected NRT render metadata: ' + name)
        if metadata['event_guid'].strip('{}').lower() != row['event_guid'].strip('{}').lower() or metadata['sha256'] != digest(raw):
            raise ValueError('Event identity/hash mismatch: ' + name)
        with wave.open(str(raw), 'rb') as audio:
            sr, channels, frames = audio.getframerate(), audio.getnchannels(), audio.getnframes()
            if audio.getsampwidth() != 2 or frames <= 0:
                raise ValueError('Expected nonempty PCM16 event render: ' + str(raw))
        milliseconds = metadata.get('event_length_ms')
        if type(milliseconds) is not int or milliseconds <= 0:
            raise ValueError('Expected positive integer event_length_ms: ' + name)
        target_frames = round(milliseconds * sr / 1000)
        if target_frames <= 0 or render_latency_frames + target_frames > frames:
            raise ValueError('Raw render cannot cover requested event timeline: ' + name)
        text = spoken_text(row['text_ru'])
        if not text:
            raise ValueError('No spoken RU text: ' + row['id'])
        rows.append({'entry': row, 'text': text, 'raw': str(raw),
                     'corrected': str((corrected / (name + '.wav')).resolve()),
                     'format': {'sample_rate': sr, 'channels': channels, 'frames': target_frames},
                     'render_metadata': metadata, 'raw_frames': frames,
                     'render_latency_frames': render_latency_frames})
    return {'target': target, 'source': SOURCE, 'physical_fsb_index_format': 'unverified',
            'output': str(output), 'rows': rows, 'game_mutations': False, 'gpu': False}

def prepare(selection, originals, output, render_latency_frames=0, target='event'):
    task = plan(selection, originals, output, render_latency_frames, target)
    # Plan validates every source and all no-overwrite conditions before writing.
    output.parent.mkdir(parents=True, exist_ok=True)
    corrected = output.parent / 'corrected-originals'
    corrected.mkdir(exist_ok=False)
    refs = {}
    for row in task['rows']:
        fmt = row['format']
        with wave.open(row['raw'], 'rb') as src:
            src.setpos(render_latency_frames)
            pcm = src.readframes(fmt['frames'])
        with open(row['corrected'], 'xb') as stream:
            with wave.open(stream, 'wb') as dst:
                dst.setparams((fmt['channels'], 2, fmt['sample_rate'], 0, 'NONE', 'NONE'))
                dst.writeframes(pcm)
        duration = fmt['frames'] / fmt['sample_rate']
        sid = row['entry']['speaker_id']
        if duration > refs.get(sid, (0, None))[0]:
            refs[sid] = (duration, row['corrected'])
    result = []
    for row in task['rows']:
        entry, fmt = row['entry'], row['format']
        reference = refs[entry['speaker_id']][1]
        result.append({'id': entry['id'], 'speaker': entry['speaker_id'], 'text': row['text'],
                       'reference': reference, 'original': row['corrected'],
                       'scene': '/'.join(a['name'] for a in reversed(entry['story'])),
                       'format': fmt, 'text_en': entry['text_en'], 'text_ru_source': entry['text_ru'],
                       'event_guid': entry['event_guid'], 'event_name': entry['event_name'],
                       'reference_sha256': digest(Path(reference)),
                       'reference_speaker_id': entry['speaker_id'], 'voice_quality': 'needs_listening',
                       'audio_source': SOURCE, 'physical_fsb_index_format': 'unverified',
                       'raw_render': row['raw'], 'raw_render_sha256': row['render_metadata']['sha256'],
                       'render_latency_frames': render_latency_frames,
                       'event_length_ms': row['render_metadata']['event_length_ms'],
                       'target_frames_formula': 'round(event_length_ms*sample_rate/1000)',
                       'evidence': entry['evidence']})
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'schema_version': 1, 'audio_source': SOURCE, 'physical_fsb_index_format': 'unverified',
                   'lines': result}, stream, ensure_ascii=False, indent=2)
    receipt = output.parent / 'preparation-receipt.json'
    receipt.write_text(json.dumps({'manifest_sha256': digest(output), 'plan': task,
                                  'perceptual_qa': 'pending', 'in_game_verified': False},
                                 ensure_ascii=False, indent=2), encoding='utf-8')
    return {'selected': len(result), 'manifest': str(output), 'source': SOURCE, 'perceptual_qa': 'pending'}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection', required=True, type=Path)
    p.add_argument('--originals', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--render-latency-frames', required=True, type=int,
                   help='Explicit renderer latency; 3072 frames was measured in the four pilot events')
    p.add_argument('--target', choices=['event'], default='event')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    try:
        operation = plan if a.dry_run else prepare
        if not a.dry_run:
            from ..universal_modder import require_toolkit
            require_toolkit()
        print(json.dumps(operation(a.selection.resolve(), a.originals.resolve(), a.output.resolve(),
                                   a.render_latency_frames, a.target), ensure_ascii=False))
    except (OSError, ValueError, KeyError, wave.Error) as exc:
        p.error(str(exc))

if __name__ == '__main__':
    main()
