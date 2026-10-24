import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

spec = importlib.util.spec_from_file_location('unity_fmod_manage', Path(__file__).resolve().parents[1] / 'integrations/unity-fmod/manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class FmodSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'; self.stage.mkdir()
        with wave.open(str(self.stage / 'line.wav'), 'wb') as wav:
            wav.setparams((1, 2, 24000, 0, 'NONE', 'NONE')); wav.writeframes(b'\1\0' * 240)
        self.entry = dict(id='line', event_guid='00000000-0000-0000-0000-000000000001', wav='line.wav', sha256=manage.digest(self.stage / 'line.wav'))
        (self.stage / 'manifest.json').write_text(json.dumps(dict(schema_version=1, entries=[self.entry])), encoding='utf-8')
        (self.stage / 'UniversalDubbing.Fmod.dll').write_bytes(b'own plugin')

    def tearDown(self):
        self.temp.cleanup()

    def test_hash_and_duplicate_fail_closed(self):
        manage.validate_manifest(self.stage / 'manifest.json')
        data = dict(schema_version=1, entries=[self.entry, self.entry])
        (self.stage / 'manifest.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            manage.validate_manifest(self.stage / 'manifest.json')

    def test_traversal_and_undeclared_files(self):
        with self.assertRaises(ValueError):
            manage.inside(self.stage, '../outside')
        (self.stage / 'original.bank').write_bytes(b'not allowed')
        game = self.root / 'game'; game.mkdir()
        files = manage.install_plan(game, self.stage, None)
        self.assertEqual(len(files), 3)
        self.assertFalse(any(p.suffix == '.bank' for p in files))

    def test_install_backup_uninstall_and_changed_file_refusal(self):
        game = self.root / 'game'; game.mkdir()
        plugin = game / 'BepInEx/plugins/UniversalDubbing/UniversalDubbing.Fmod.dll'
        plugin.parent.mkdir(parents=True); plugin.write_bytes(b'previous own plugin')
        receipt = self.root / 'receipt.json'
        args = argparse.Namespace(game=str(game), game_exe='Game.exe', stage=str(self.stage), loader_root=None, receipt=str(receipt), apply=True)
        with patch.object(manage, 'closed_game'):
            manage.install(args)
            self.assertEqual(plugin.read_bytes(), b'own plugin')
            plugin.write_bytes(b'user change')
            with self.assertRaisesRegex(ValueError, 'changed'):
                manage.uninstall(args)
            plugin.write_bytes(b'own plugin')
            manage.uninstall(args)
        self.assertEqual(plugin.read_bytes(), b'previous own plugin')
        self.assertFalse((plugin.parent / 'manifest.json').exists())

    def test_interrupted_install_before_and_after_replace_can_roll_back(self):
        for failure in ('copy', 'before_replace', 'after_replace'):
            with self.subTest(failure=failure):
                game = self.root / failure; game.mkdir()
                plugin = game / 'BepInEx/plugins/UniversalDubbing/UniversalDubbing.Fmod.dll'
                plugin.parent.mkdir(parents=True); plugin.write_bytes(b'old plugin')
                receipt = self.root / (failure + '.json')
                args = argparse.Namespace(game=str(game), game_exe='Game.exe', stage=str(self.stage), loader_root=None, receipt=str(receipt), apply=True)
                real_copy, real_replace = manage.shutil.copy2, Path.replace

                def copy(source, target, *a, **kw):
                    if failure == 'copy' and Path(source) == self.stage / 'UniversalDubbing.Fmod.dll':
                        raise OSError('injected copy interruption')
                    return real_copy(source, target, *a, **kw)

                def replace(source, target):
                    if Path(target) == plugin:
                        if failure == 'before_replace':
                            raise OSError('injected before replace')
                        result = real_replace(source, target)
                        if failure == 'after_replace':
                            raise OSError('injected after replace')
                        return result
                    return real_replace(source, target)

                with patch.object(manage, 'closed_game'), patch.object(manage.shutil, 'copy2', side_effect=copy), patch.object(Path, 'replace', replace):
                    with self.assertRaises(OSError):
                        manage.install(args)
                saved = json.loads(receipt.read_text())
                self.assertEqual(saved['state'], 'installing')
                self.assertEqual(saved['files'][-1]['state'], 'pending')
                with patch.object(manage, 'closed_game'):
                    manage.uninstall(args)
                    manage.uninstall(args)
                self.assertEqual(plugin.read_bytes(), b'old plugin')
                self.assertFalse((plugin.parent / 'manifest.json').exists())

    def test_interrupted_rollback_resumes_and_preserves_unknown_edits(self):
        game = self.root / 'rollback'; game.mkdir()
        plugin = game / 'BepInEx/plugins/UniversalDubbing/UniversalDubbing.Fmod.dll'
        plugin.parent.mkdir(parents=True); plugin.write_bytes(b'old plugin')
        manifest = plugin.parent / 'manifest.json'; manifest.write_bytes(b'old manifest')
        receipt = self.root / 'rollback.json'
        args = argparse.Namespace(game=str(game), game_exe='Game.exe', stage=str(self.stage), loader_root=None, receipt=str(receipt), apply=True)
        real_replace = Path.replace
        def replace(source, target):
            if Path(target) == manifest:
                raise OSError('injected rollback interruption')
            return real_replace(source, target)
        with patch.object(manage, 'closed_game'):
            manage.install(args)
            with patch.object(Path, 'replace', replace), self.assertRaises(OSError):
                manage.uninstall(args)
            self.assertEqual(plugin.read_bytes(), b'old plugin')
            self.assertEqual(json.loads(receipt.read_text())['state'], 'uninstalling')
            plugin.write_bytes(b'unknown user edit')
            with self.assertRaisesRegex(ValueError, 'changed'):
                manage.uninstall(args)
            plugin.write_bytes(b'old plugin')
            manage.uninstall(args)
        self.assertEqual(plugin.read_bytes(), b'old plugin')
        self.assertEqual(manifest.read_bytes(), b'old manifest')
        self.assertEqual(json.loads(receipt.read_text())['state'], 'uninstalled')

    def test_loader_conflict_does_not_overwrite(self):
        game = self.root / 'game'; game.mkdir(); (game / 'winhttp.dll').write_bytes(b'existing')
        loader = self.root / 'loader'; loader.mkdir(); (loader / 'winhttp.dll').write_bytes(b'new loader')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            manage.install_plan(game, self.stage, loader)

    def test_stage_applies_game_bus_config(self):
        config = self.root / 'integration.json'
        config.write_text(json.dumps(dict(schema_version=1, voice_bus='bus:/CustomVoice')))
        target = self.root / 'new-stage'
        args = argparse.Namespace(manifest=str(self.stage / 'manifest.json'), plugin=str(self.stage / 'UniversalDubbing.Fmod.dll'), output=str(target), apply=True, integration_config=str(config))
        manage.stage(args)
        data = manage.validate_manifest(target / 'manifest.json')
        self.assertEqual(data['voice_bus'], 'bus:/CustomVoice')


if __name__ == '__main__':
    unittest.main()
