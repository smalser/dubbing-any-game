"""Actual C# parser executable tests; set UNITY_FMOD_MANIFEST_CHECK and UNITY_FMOD_DOTNET."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('UNITY_FMOD_MANIFEST_CHECK') and os.environ.get('UNITY_FMOD_DOTNET'), 'C# parser harness not configured')
class ActualManifestParserTests(unittest.TestCase):
    def run_parser(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'
            path.write_text(text, encoding='utf-8')
            return subprocess.run([os.environ['UNITY_FMOD_DOTNET'], os.environ['UNITY_FMOD_MANIFEST_CHECK'], str(path)], text=True, capture_output=True)

    def manifest(self):
        return {'schema_version': 1, 'entries': [{'id': 'line1', 'event_guid': '00000000-0000-0000-0000-000000000001', 'wav': 'audio/line1.wav', 'sha256': 'a'*64}]}

    def test_actual_good_parser_and_extra_metadata(self):
        data = self.manifest(); data['coverage'] = {'selected': 1}
        result = self.run_parser(json.dumps(data))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('schema=1 count=1', result.stdout)

    def test_reject_wrong_schema_type_and_null_entries(self):
        for change in ({'schema_version': '1'}, {'schema_version': 0}, {'entries': None}, {'entries': []}):
            data = self.manifest(); data.update(change)
            self.assertEqual(self.run_parser(json.dumps(data)).returncode, 2)

    def test_reject_duplicates_traversal_and_bad_hash(self):
        for key, value in [('wav', '../outside.wav'), ('id', 'NUL'), ('sha256', 'bad'), ('sound_id', 'not-a-number')]:
            data = self.manifest(); data['entries'][0][key] = value
            self.assertEqual(self.run_parser(json.dumps(data)).returncode, 2)
        data = self.manifest(); data['entries'] *= 2
        self.assertEqual(self.run_parser(json.dumps(data)).returncode, 2)

    def test_reject_duplicate_json_keys_and_trailing_json(self):
        self.assertEqual(self.run_parser('{"schema_version":1,"schema_version":2,"entries":[]}').returncode, 2)
        self.assertEqual(self.run_parser(json.dumps(self.manifest()) + '{}').returncode, 2)


if __name__ == '__main__':
    unittest.main()
