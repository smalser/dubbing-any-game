"""Regression tests for the exact verified speech → FMOD runtime boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from dubbing.integrations.rue_valley.export import export, plan


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RueValleyExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'prepared.json'
        self.selection = self.root / 'selected.json'
        self.generated = self.root / 'generated'
        (self.generated / 'fitted').mkdir(parents=True)
        self.output = self.root / 'runtime'
        self.guid = 'af82429b-99d5-4e6d-a3c0-21c238e6913f'
        self.ident = '72057632692673839'
        self.wav = self.generated / 'fitted' / (self.ident + '.wav')
        with wave.open(str(self.wav), 'wb') as stream:
            stream.setparams((2, 2, 48000, 0, 'NONE', 'NONE'))
            stream.writeframes(b'\x01\x00\x02\x00' * 96)
        self.prepared = {'schema_version': 1, 'lines': [
            {'id': self.ident, 'event_guid': '{' + self.guid + '}',
             'speaker': '72057658462437409', 'reference_speaker_id': '72057658462437409',
             'format': {'sample_rate': 48000, 'channels': 2, 'frames': 96}}]}
        self.chosen = {'entries': [
            {'id': self.ident, 'event_guid': self.guid.upper(),
             'speaker_id': '72057658462437409', 'sound_id': '72057735771854730'}]}
        self.save(self.manifest, self.prepared)
        self.save(self.selection, self.chosen)
        self.receipt = {'test_tones': False, 'manifest_sha256': sha(self.manifest),
                        'count': 1, 'files': [{'id': self.ident, 'sha256': sha(self.wav)}]}
        self.save_receipt()

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def save_receipt(self):
        self.save(self.generated / 'verification.json', self.receipt)

    def check_plan(self):
        return plan(self.manifest, self.selection, self.generated, self.output)

    def test_verification_manifest_hash_mismatch_rejected_before_export(self):
        self.prepared['lines'][0]['format']['frames'] = 97
        self.save(self.manifest, self.prepared)
        with self.assertRaisesRegex(ValueError, 'exact prepared manifest'):
            self.check_plan()
        self.assertFalse(self.output.exists())

    def test_test_tones_and_missing_real_speech_flag_rejected(self):
        for flag in (True, None, 0):
            with self.subTest(flag=flag):
                self.receipt['test_tones'] = flag
                self.save_receipt()
                with self.assertRaisesRegex(ValueError, 'verified real speech'):
                    self.check_plan()
                self.assertFalse(self.output.exists())

    def test_missing_selected_or_verified_id_rejected(self):
        self.receipt['files'] = []
        self.receipt['count'] = 0
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'IDs must match exactly'):
            self.check_plan()
        self.receipt['files'] = [{'id': self.ident, 'sha256': sha(self.wav)}]
        self.receipt['count'] = 1
        self.save_receipt()
        self.save(self.selection, {'entries': []})
        with self.assertRaisesRegex(ValueError, 'IDs must match exactly'):
            self.check_plan()
        self.assertFalse(self.output.exists())

    def test_fitted_sha_mismatch_rejected_before_export(self):
        # Mutate the fitted PCM after verification while preserving a valid WAV.
        with wave.open(str(self.wav), 'wb') as stream:
            stream.setparams((2, 2, 48000, 0, 'NONE', 'NONE'))
            stream.writeframes(b'\x03\x00\x04\x00' * 96)
        with self.assertRaisesRegex(ValueError, 'Verified WAV changed'):
            self.check_plan()
        self.assertFalse(self.output.exists())

    def test_success_exports_exact_event_sound_and_verified_audio(self):
        before = self.wav.read_bytes()
        expected = {'id': self.ident, 'event_guid': self.guid,
                    'sound_id': '72057735771854730', 'wav': 'audio/' + self.ident + '.wav',
                    'sha256': sha(self.wav)}
        result = self.check_plan()
        self.assertEqual(result['entries'], [expected])
        self.assertFalse(self.output.exists(), 'planning must not create runtime output')
        result = export(self.manifest, self.selection, self.generated, self.output)
        self.assertEqual(result['entries'], [expected])
        self.assertEqual((self.output / expected['wav']).read_bytes(), before)
        self.assertEqual(self.wav.read_bytes(), before)
        saved = json.loads((self.output / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, result)
        self.assertEqual(result['source_manifest_sha256'], sha(self.manifest))
        self.assertEqual(result['selection_sha256'], sha(self.selection))
        self.assertEqual(result['verification_sha256'], sha(self.generated / 'verification.json'))
        self.assertEqual(result['coverage'], 'selected_pilot_only')
        self.assertFalse(result['in_game_verified'])
        self.assertEqual(result['perceptual_qa'], 'pending')


if __name__ == '__main__':
    unittest.main()
