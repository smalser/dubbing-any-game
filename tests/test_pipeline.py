"""Integration checks on disposable fixtures; no game assets or GPU required."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave
import struct
import math
import zipfile
import sys

from dubbing.cli import main, read, locked


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'out'
        ref = self.root / 'ref.wav'
        with wave.open(str(ref), 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            f.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(i * 2 * math.pi * 330 / 24000)))
                                  for i in range(24000)))
        self.row = {'id': 'line-1', 'speaker': 'speaker', 'text': 'Тест',
                    'reference': 'ref.wav', 'original': 'ref.wav', 'scene': 'start',
                    'format': {'sample_rate': 24000, 'channels': 1, 'frames': 24000}}
        self.manifest = self.root / 'manifest.json'
        self.save()

    def save(self, rows=None):
        self.manifest.write_text(json.dumps({'schema_version': 1, 'lines': rows or [self.row]}), encoding='utf-8')

    def run_cli(self, command, *extra):
        args = [command, '--manifest', str(self.manifest), '--output', str(self.out),
                '--adapter', 'mock', '--device', 'cpu', '--lock-dir', str(self.root / 'locks'), *extra]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(args)

    def test_dry_run_has_no_outputs(self):
        self.assertEqual(self.run_cli('generate', '--dry-run'), 0)
        self.assertFalse(self.out.exists())

    def test_resume_and_text_invalidation(self):
        self.run_cli('generate')
        p = self.out / 'raw' / 'line-1.wav'
        before = p.stat().st_mtime_ns
        self.run_cli('generate')
        self.assertEqual(before, p.stat().st_mtime_ns)
        self.assertEqual(read(self.out / 'status.json')['skipped'], 1)
        self.row['text'] = 'Другой текст'
        self.save()
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['skipped'], 0)

    def test_corruption_invalidates_cache(self):
        self.run_cli('generate')
        (self.out / 'raw' / 'line-1.wav').write_bytes(b'bad')
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['skipped'], 0)

    def test_batch_recovery_rewrites_whole_group(self):
        other = dict(self.row, id='line-2')
        self.save([self.row, other])
        self.run_cli('generate')
        (self.out / 'raw' / 'line-2.json').unlink()
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['skipped'], 0)

    def test_reference_hash_invalidation(self):
        self.run_cli('generate')
        ref = self.root / 'ref.wav'
        data = bytearray(ref.read_bytes())
        data[-5] ^= 1
        ref.write_bytes(data)
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['skipped'], 0)

    def test_reject_path_traversal_and_duplicates(self):
        self.row['id'] = '../escape'
        self.save()
        with self.assertRaises(SystemExit):
            self.run_cli('plan')
        self.row['id'] = 'line-1'
        self.save([self.row, self.row])
        with self.assertRaises(SystemExit):
            self.run_cli('plan')

    def test_stop_and_lock(self):
        self.out.mkdir()
        (self.out / 'STOP').touch()
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['phase'], 'stopped')
        self.assertFalse((self.out / 'raw').exists())
        path = self.root / 'lock'
        with locked(path):
            with self.assertRaises(ValueError):
                with locked(path):
                    pass
        self.assertFalse(path.exists())

    def test_config_override_and_exclusions(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps({'adapter': 'mock', 'batch_size': 2, 'device': 'cpu'}), encoding='utf-8')
        self.save([self.row, {'id': 'excluded', 'status': 'unknown', 'reason': 'speaker unknown'}])
        self.run_cli('generate', '--config', str(config), '--batch-size', '1')
        self.assertEqual(read(self.out / 'generation-config.json')['batch_size'], 1)
        self.assertFalse((self.out / 'raw' / 'excluded.wav').exists())

    def test_failure_receipt_and_blockers(self):
        self.run_cli('generate')
        with self.assertRaises(SystemExit):
            self.run_cli('fit', '--batch-size', '1')
        self.assertEqual(read(self.out / 'status.json')['phase'], 'failed')
        self.assertFalse((self.out / 'RUNNING.lock').exists())
        self.row['blockers'] = ['ambiguous speaker']
        self.save()
        with self.assertRaises(SystemExit):
            self.run_cli('plan')

    def test_external_adapter(self):
        module = self.root / 'custom_test_voice.py'
        module.write_text('from dubbing.adapters.tts import Mock\nclass Voice(Mock):\n    pass\n', encoding='utf-8')
        sys.path.insert(0, str(self.root))
        try:
            self.run_cli('generate', '--adapter', 'custom_test_voice:Voice', '--adapter-options', '{"example": true}')
            cfg = read(self.out / 'generation-config.json')
            self.assertIn('adapter_sha256', cfg)
            self.assertEqual(cfg['adapter_options'], {'example': True})
        finally:
            sys.path.remove(str(self.root))
            sys.modules.pop('custom_test_voice', None)

    def test_stereo_resampling(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg not installed')
        self.row['format'] = {'sample_rate': 48000, 'channels': 2, 'frames': 48000}
        self.row.pop('original')
        self.save()
        for command in ('generate', 'fit', 'verify'):
            self.run_cli(command, '--loudness', 'none')
        with wave.open(str(self.out / 'fitted' / 'line-1.wav')) as f:
            self.assertEqual((f.getframerate(), f.getnchannels(), f.getnframes()), (48000, 2, 48000))

    def test_full_export_and_stale_rejection(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg not installed')
        for cmd in ['generate', 'fit', 'verify', 'preview', 'package']:
            self.assertEqual(self.run_cli(cmd), 0)
        with zipfile.ZipFile(self.out / 'audio-export.zip') as z:
            self.assertEqual(set(z.namelist()), {'manifest.json', 'audio/line-1.wav'})
            receipt = json.loads(z.read('manifest.json'))
            self.assertTrue(receipt['test_tones'])
            self.assertFalse(receipt['in_game_verified'])
        with wave.open(str(self.out / 'fitted' / 'line-1.wav')) as f:
            self.assertEqual(f.getnframes(), 24000)
        self.row['text'] = 'Изменено'
        self.save()
        with self.assertRaises(SystemExit):
            self.run_cli('package')

    def test_speedup_bypass_and_pitch_preservation(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg not installed')
        import numpy as np
        import soundfile as sf
        self.row['format']['frames'] = 6000
        self.row.pop('original')
        self.save()
        self.run_cli('generate', '--loudness', 'none')
        try:
            self.run_cli('fit', '--loudness', 'none')
        except SystemExit:
            self.fail('FFmpeg with rubberband filter is required for speedup test')
        a, rate = sf.read(self.out / 'fitted' / 'line-1.wav')
        peak_frequency = np.argmax(np.abs(np.fft.rfft(a))) * rate / len(a)
        self.assertLess(abs(peak_frequency - 220), 5)
        self.assertEqual(len(a), 6000)
        self.assertEqual(read(self.out / 'fitted' / 'line-1.json')['tempo'], 2)


if __name__ == '__main__':
    unittest.main()
