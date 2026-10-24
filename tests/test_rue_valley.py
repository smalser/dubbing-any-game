import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from dubbing.integrations.rue_valley.prepare import prepare, plan, spoken_text
from dubbing.integrations.rue_valley.mapping import join_objects

class RueValleyTests(unittest.TestCase):
    def test_context_does_not_become_speech(self):
        self.assertEqual(spoken_text('<i>Слова</i>\nгероя.§Он смотрит.'), 'Слова героя.')
        self.assertEqual(spoken_text('§Только описание'), '')

    def fixture(self, root):
        row = dict(id='123', speaker='Dr. Finck', speaker_id='42', text_ru='Привет.§', text_en='Hi.§', event_name='DFr_A', event_guid='{00000000-0000-0000-0000-000000000001}', story=[], evidence={})
        selection = root / 'selected.json'
        selection.write_text(json.dumps({'entries': [row]}), encoding='utf-8')
        raw = root / 'DFr_A.wav'
        with wave.open(str(raw), 'wb') as w:
            w.setparams((1, 2, 1000, 0, 'NONE', 'NONE'))
            w.writeframes(struct.pack('<10h', *range(10)))
        meta = {'event_guid': row['event_guid'], 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(), 'method': 'FMOD Studio WAVWRITER_NRT event render', 'event_length_ms': 5}
        (root / 'DFr_A.json').write_text(json.dumps(meta), encoding='utf-8')
        return row, selection, raw

    def test_timeline_correction_preserves_raw_and_plan_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row, selection, raw = self.fixture(root)
            before = raw.read_bytes()
            output = root / 'pilot' / 'manifest.json'
            task = plan(selection, root, output, 2, 'event')
            self.assertEqual(task['rows'][0]['format']['frames'], 5)
            self.assertFalse(output.parent.exists())
            prepare(selection, root, output, 2, 'event')
            line = json.loads(output.read_text(encoding='utf-8'))['lines'][0]
            self.assertEqual(line['reference_speaker_id'], line['speaker'])
            self.assertEqual(line['format']['frames'], 5)
            self.assertEqual(line['physical_fsb_index_format'], 'unverified')
            with wave.open(line['original'], 'rb') as w:
                self.assertEqual(struct.unpack('<5h', w.readframes(5)), (2, 3, 4, 5, 6))
            self.assertEqual(raw.read_bytes(), before)
            manifest_before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                prepare(selection, root, output, 2)
            self.assertEqual(output.read_bytes(), manifest_before)
            self.assertEqual(raw.read_bytes(), before)

    def test_player_and_insufficient_render_are_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row, selection, raw = self.fixture(root)
            output = root / 'pilot' / 'manifest.json'
            with self.assertRaisesRegex(ValueError, 'cannot cover'):
                prepare(selection, root, output, 6)
            self.assertFalse(output.parent.exists())
            row['speaker'] = 'You'
            selection.write_text(json.dumps({'entries': [row]}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'excluded'):
                prepare(selection, root, output)

    def test_mapping_requires_language_manager_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'objects.jsonl'; source.write_text('', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'LocalizationManager'):
                join_objects(source, Path(td) / 'result')

    def test_mapping_duplicate_objects_never_silently_override(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'objects.jsonl'
            item = {'class': 'Character', 'path_id': 1, 'data': {'id': 42}}
            source.write_text(json.dumps(item) + '\n' + json.dumps(item), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate Articy object ID'):
                join_objects(source, Path(td) / 'out')

    def test_existing_mapping_and_bad_timeline_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, selection, _ = self.fixture(root)
            existing = root / 'existing'; existing.mkdir()
            with self.assertRaisesRegex(ValueError, 'new directory'):
                join_objects(root / 'not-read', existing)
            metadata = root / 'DFr_A.json'
            data = json.loads(metadata.read_text()); data['event_length_ms'] = True
            metadata.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                plan(selection, root, root / 'out/manifest.json')

if __name__ == '__main__':
    unittest.main()
