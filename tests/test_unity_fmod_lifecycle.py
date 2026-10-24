import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('UNITY_FMOD_LIFECYCLE_CHECK') and os.environ.get('UNITY_FMOD_DOTNET'), 'Actual C# lifecycle harness not configured')
class ActualLifecycleTests(unittest.TestCase):
    def test_live_volume_short_wav_stop_and_reuse(self):
        result = subprocess.run([os.environ['UNITY_FMOD_DOTNET'], os.environ['UNITY_FMOD_LIFECYCLE_CHECK']], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('reused instance PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
