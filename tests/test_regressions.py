"""Fault injection and boundary checks for defects found in independent review."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import soundfile as sf
import test_pipeline
from dubbing import processing, synthesis
from dubbing.adapters.tts import Mock, create
from dubbing.cli import main
from dubbing.storage import digest, locked, read, write
from tools.source_release import build, source_files


class RegressionTests(unittest.TestCase):
    setUp = test_pipeline.PipelineTests.setUp
    save = test_pipeline.PipelineTests.save
    run_cli = test_pipeline.PipelineTests.run_cli

    def assert_cli_error(self, command, *extra):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(command, *extra)
        self.assertEqual(caught.exception.code, 2)

    def test_changed_neighbor_invalidates_every_batch_member(self):
        neighbor = dict(self.row, id='line-2')
        self.save([self.row, neighbor])
        self.run_cli('generate')
        before = read(self.out / 'raw' / 'line-1.json')['fingerprint']
        neighbor['text'] = 'A much longer neighboring utterance changes padded batch shape'
        self.save([self.row, neighbor])
        self.run_cli('generate')
        self.assertNotEqual(before, read(self.out / 'raw' / 'line-1.json')['fingerprint'])
        self.assertEqual(read(self.out / 'status.json')['generated'], 2)

    def test_mid_commit_failure_cannot_pass_as_complete_batch(self):
        self.save([self.row, dict(self.row, id='line-2')])
        self.run_cli('generate')
        # Force regeneration, retaining both old per-line files and metadata.
        next((self.out / 'batches').glob('*.json')).unlink()
        real_write = synthesis.write

        def interrupted(path, value):
            if path.name == 'line-2.json':
                raise OSError('simulated disk failure during batch commit')
            real_write(path, value)

        with patch.object(synthesis, 'write', side_effect=interrupted):
            self.assert_cli_error('generate')
        self.assertEqual(list((self.out / 'batches').glob('*.json')), [])
        self.assert_cli_error('fit')
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['generated'], 2)
        self.assertFalse((self.out / 'RUNNING.lock').exists())

    def test_invalid_second_waveform_commits_nothing(self):
        self.save([self.row, dict(self.row, id='line-2')])
        with patch.object(Mock, 'synthesize', return_value=[(np.ones(100) * .1, 24000),
                                                         (np.array([float('nan')]), 24000)]):
            self.assert_cli_error('generate')
        self.assertFalse((self.out / 'raw').exists())
        self.assertFalse((self.out / 'batches').exists())

    def test_invalid_adapter_return_types_are_clear_errors(self):
        invalid = [None, [(np.ones(10) * .1, True)], [(np.ones(10) * .1, 24000.5)],
                   [(np.ones((8, 9)) * .1, 24000)], [(np.array([1j]), 24000)],
                   [('not audio', 24000)], [(.1, 24000)], [('missing-rate',)]]
        for result in invalid:
            with self.subTest(result=repr(result)):
                with patch.object(Mock, 'synthesize', return_value=result):
                    self.assert_cli_error('generate')
                self.assertFalse((self.out / 'RUNNING.lock').exists())

    def test_adapter_class_contract(self):
        with self.assertRaisesRegex(ValueError, 'class not found'):
            create('dubbing.adapters.tts:Absent')
        with self.assertRaisesRegex(ValueError, 'must be a class'):
            create('dubbing.adapters.tts:create')
        with self.assertRaisesRegex(ValueError, 'must implement'):
            create('builtins:object')

    def test_stop_after_model_load_never_starts_synthesis(self):
        def stop_on_load(adapter, cfg):
            (self.out / 'STOP').touch()
        with patch.object(Mock, 'load', stop_on_load), patch.object(Mock, 'synthesize') as synthesize:
            self.assertEqual(self.run_cli('generate'), 3)
            synthesize.assert_not_called()
        self.assertEqual(read(self.out / 'status.json')['phase'], 'stopped')
        (self.out / 'STOP').unlink()
        self.assertEqual(self.run_cli('generate'), 0)

    def test_replacement_lock_is_not_removed(self):
        lock = self.root / 'lock'
        with locked(lock):
            write(lock, {'pid': 123, 'token': 'different-owner'})
        self.assertTrue(lock.exists())
        self.assertEqual(synthesis.resource_name('cuda'), synthesis.resource_name('cuda:0'))

    def test_portable_ids_and_strict_manifest_types(self):
        for ident in ('CON', 'nul', 'LPT1', 'COM9'):
            self.row['id'] = ident
            self.save()
            self.assert_cli_error('plan')
        self.row['id'] = 'line-1'
        self.save([self.row, dict(self.row, id='LINE-1')])
        self.assert_cli_error('plan')
        for value in (12, None, [], True):
            self.row['original'] = value
            self.save()
            self.assert_cli_error('plan')

    def test_unknown_status_and_unexplained_exclusion_fail(self):
        self.save([self.row, {'id': 'excluded', 'status': 'raedy', 'reason': 'typo'}])
        self.assert_cli_error('plan')
        self.save([self.row, {'id': 'excluded', 'status': 'unknown'}])
        self.assert_cli_error('plan')

    def test_nonselected_missing_assets_do_not_block_selection(self):
        self.save([self.row, dict(self.row, id='later', original='not-extracted.wav')])
        self.assertEqual(self.run_cli('plan', '--ids', 'line-1'), 0)
        self.assert_cli_error('plan')

    def test_json_duplicates_nonfinite_and_config_types(self):
        config = self.root / 'config.json'
        for payload in ('{"device": null}', '{"model": []}', '{"batch_size": true}',
                        '{"device":"cpu","device":"cuda"}', '{"adapter_options":{"t":NaN}}'):
            config.write_text(payload, encoding='utf-8')
            self.assert_cli_error('plan', '--config', str(config))
        self.assert_cli_error('plan', '--adapter-options', '{"t":NaN}')

    def test_boolean_config_can_be_overridden_explicitly(self):
        config = self.root / 'config.json'
        write(config, {'dry_run': True, 'allow_download': True})
        self.run_cli('generate', '--config', str(config), '--no-dry-run', '--no-allow-download')
        self.assertTrue((self.out / 'raw' / 'line-1.wav').exists())
        self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')

    def test_source_inputs_cannot_be_overwritten_by_output(self):
        (self.out / 'raw').mkdir(parents=True)
        source = self.out / 'raw' / 'line-1.wav'
        shutil.copyfile(self.root / 'ref.wav', source)
        original_hash = digest(source)
        self.row['reference'] = str(source)
        self.save()
        self.assert_cli_error('generate')
        self.assertEqual(digest(source), original_hash)

    def test_processing_changes_do_not_invalidate_raw(self):
        self.run_cli('generate')
        raw = self.out / 'raw' / 'line-1.wav'
        before = raw.stat().st_mtime_ns
        with patch.object(processing, 'processing_identity', return_value={'implementation': 'new-fit'}):
            self.run_cli('generate', '--gain-db', '-2', '--loudness', 'none')
        self.assertEqual(raw.stat().st_mtime_ns, before)
        self.assertEqual(read(self.out / 'status.json')['skipped'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_fit_cache_processing_identity_and_raw_preservation(self):
        self.run_cli('generate')
        self.run_cli('fit')
        raw = self.out / 'raw' / 'line-1.wav'
        fitted = self.out / 'fitted' / 'line-1.wav'
        raw_hash, before = digest(raw), fitted.stat().st_mtime_ns
        self.run_cli('fit')
        self.assertEqual(fitted.stat().st_mtime_ns, before)
        self.assertEqual(read(self.out / 'status.json')['skipped'], 1)
        with patch.object(processing, 'processing_identity', return_value={'implementation': 'new-fit'}):
            self.assert_cli_error('verify')
            self.run_cli('fit')
            self.run_cli('verify')
        self.assertEqual(digest(raw), raw_hash)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_short_audio_bypasses_stretch_and_peak_cap_is_real(self):
        self.run_cli('generate')
        real_run = processing.subprocess.run
        commands = []

        def record(cmd, **kwargs):
            commands.append(cmd)
            return real_run(cmd, **kwargs)

        with patch.object(processing.subprocess, 'run', side_effect=record):
            self.run_cli('fit', '--loudness', 'none', '--gain-db', '50', '--peak-db', '-6')
        self.assertFalse(any('rubberband' in part for cmd in commands for part in cmd))
        samples, rate = sf.read(self.out / 'fitted' / 'line-1.wav')
        self.assertLessEqual(np.max(np.abs(samples)), 10 ** (-6 / 20))
        self.assertEqual(len(samples), 24000)
        self.assertTrue(np.all(samples[12000:] == 0))
        self.run_cli('verify', '--loudness', 'none', '--gain-db', '50', '--peak-db', '-6')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_float_resampler_overshoot_is_capped_before_pcm(self):
        self.run_cli('generate')
        real_run = processing.subprocess.run
        def converted_overshoot(cmd, **kwargs):
            if '-version' in cmd:
                return real_run(cmd, **kwargs)
            sf.write(cmd[-1], np.sin(np.arange(12000) * .1) * 1.02, 24000, subtype='FLOAT')
        with patch.object(processing.subprocess, 'run', side_effect=converted_overshoot):
            self.run_cli('fit', '--loudness', 'none')
        self.run_cli('verify', '--loudness', 'none')

    def test_unrepresentable_pcm_peak_is_rejected_before_generation(self):
        self.assert_cli_error('generate', '--peak-db', '-95')
        self.assertFalse(self.out.exists())

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_ffmpeg_build_identity_changes_behind_same_launcher(self):
        from types import SimpleNamespace
        real_run = processing.subprocess.run
        before = processing.processing_identity(SimpleNamespace(ffmpeg='ffmpeg'))
        def changed_build(cmd, **kwargs):
            result = real_run(cmd, **kwargs)
            result.stdout += '\nchanged linked FFmpeg build\n'
            return result
        with patch.object(processing.subprocess, 'run', side_effect=changed_build):
            after = processing.processing_identity(SimpleNamespace(ffmpeg='ffmpeg'))
        self.assertEqual(before['ffmpeg_sha256'], after['ffmpeg_sha256'])
        self.assertNotEqual(before['ffmpeg_version'], after['ffmpeg_version'])

    def test_doctor_missing_runtime_is_not_success(self):
        import importlib.metadata
        real_version = importlib.metadata.version
        def no_numpy(name):
            if name == 'numpy':
                raise importlib.metadata.PackageNotFoundError(name)
            return real_version(name)
        with patch('dubbing.platforms.importlib.metadata.version', side_effect=no_numpy):
            self.assertEqual(self.run_cli('doctor'), 2)

    def test_malformed_cache_metadata_regenerates(self):
        self.run_cli('generate')
        write(self.out / 'raw' / 'line-1.json', [])
        self.run_cli('generate')
        self.assertEqual(read(self.out / 'status.json')['generated'], 1)


class SourceReleaseTests(unittest.TestCase):
    def test_exact_inventory_reproducibility_and_source_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tools').mkdir()
            (root / 'docs').mkdir()
            (root / 'tools' / 'source-files.txt').write_text('README.md\n', encoding='utf-8')
            (root / 'README.md').write_text('Reviewed source\n', encoding='utf-8')
            (root / 'docs' / 'secret.txt').write_text('must stay local', encoding='utf-8')
            (root / 'docs' / 'voice.wav').write_bytes(b'private audio')
            first = build(root, root / 'a.zip')
            os.utime(root / 'README.md', (123456, 123456))
            second = build(root, root / 'b.zip')
            self.assertEqual(first, second)
            with zipfile.ZipFile(root / 'a.zip') as archive:
                self.assertEqual(archive.namelist(), ['README.md'])
            with self.assertRaisesRegex(ValueError, 'suffix|overwrite'):
                build(root, root / 'README.md')
            with self.assertRaisesRegex(ValueError, 'suffix'):
                build(root, root / 'bad.sha256')
            (root / 'tools' / 'source-files.txt').write_text('../outside\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                source_files(root)


if __name__ == '__main__':
    unittest.main()
