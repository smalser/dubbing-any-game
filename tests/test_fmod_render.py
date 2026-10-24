import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dubbing.integrations.fmod.render import main, render


class FmodRenderTests(unittest.TestCase):
    def test_dry_run_never_loads_library(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'
            source.write_bytes(b'fixture')
            argv = ['render', '--native', str(source), '--bank', str(source),
                    '--guid', 'af82429b-99d5-4e6d-a3c0-21c238e6913f',
                    '--output', str(Path(folder) / 'out.wav'), '--dry-run']
            captured = io.StringIO()
            with patch('sys.argv', argv), patch('ctypes.CDLL') as dll, contextlib.redirect_stdout(captured):
                main()
            dll.assert_not_called()
            self.assertEqual(json.loads(captured.getvalue())['event_guid'], argv[6])

    def test_direct_render_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'existing.wav'
            output.write_bytes(b'preserve')
            with patch('ctypes.CDLL') as dll:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    render(Path('unused'), [], '', output)
            dll.assert_not_called()
            self.assertEqual(output.read_bytes(), b'preserve')

    def test_direct_render_has_finite_budget(self):
        with patch('ctypes.CDLL') as dll:
            with self.assertRaisesRegex(ValueError, 'max-seconds'):
                render(Path('unused'), [], '', Path('unused-output.wav'), 121)
            dll.assert_not_called()

    def test_existing_metadata_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'out.wav'
            output.with_suffix('.json').write_text('preserve')
            with patch('ctypes.CDLL') as dll:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    render(Path('unused'), [], '', output)
                dll.assert_not_called()
