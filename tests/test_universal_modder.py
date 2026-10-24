"""Game toolkit requirement must be explicit and must not invoke generation APIs."""
import importlib.metadata
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from dubbing.integrations.universal_modder import REVISION, inspect_toolkit, require_toolkit


class ToolkitTests(unittest.TestCase):
    def test_missing_dependency_is_actionable(self):
        with patch('dubbing.integrations.universal_modder.importlib.metadata.distribution',
                   side_effect=importlib.metadata.PackageNotFoundError('universal-modder')):
            result = inspect_toolkit()
            self.assertFalse(result['passed'])
            self.assertIn('[game]', result['install'])
            with self.assertRaisesRegex(ValueError, 'required'):
                require_toolkit()

    def test_wrong_revision_does_not_run_tool(self):
        dist = Mock(version='0.2.0')
        dist.read_text.return_value = json.dumps({'vcs_info': {'commit_id': 'wrong'}})
        with patch('dubbing.integrations.universal_modder.importlib.metadata.distribution', return_value=dist), \
             patch('dubbing.integrations.universal_modder.subprocess.run') as run:
            self.assertFalse(inspect_toolkit()['passed'])
            run.assert_not_called()

    def test_exact_requirement_checks_only_cli_version(self):
        dist = Mock(version='0.2.0')
        dist.read_text.return_value = json.dumps({'vcs_info': {'commit_id': REVISION}})
        completed = subprocess.CompletedProcess([], 0, stdout='universal-modder 0.2.0\n', stderr='')
        with patch('dubbing.integrations.universal_modder.importlib.metadata.distribution', return_value=dist), \
             patch('dubbing.integrations.universal_modder.subprocess.run', return_value=completed) as run:
            self.assertTrue(require_toolkit()['passed'])
            self.assertEqual(run.call_args.args[0][-3:], ['-m', 'um', '--version'])

    def test_malformed_install_metadata_is_a_failed_check(self):
        dist = Mock(version='0.2.0')
        dist.read_text.return_value = '[]'
        with patch('dubbing.integrations.universal_modder.importlib.metadata.distribution', return_value=dist):
            self.assertFalse(inspect_toolkit()['passed'])


if __name__ == '__main__':
    unittest.main()
