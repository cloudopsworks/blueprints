"""Operator state examples are documentation, not application configuration."""
from pathlib import Path
import unittest


BLUEPRINTS = Path(__file__).resolve().parents[2]
WORKSPACE = BLUEPRINTS.parent
OPERATORS = BLUEPRINTS / 'docs/monorepo/operator-settings/backend'


class BackendConfigurationBoundaryTests(unittest.TestCase):
    def test_backend_examples_exist_only_in_platform_operator_documentation(self):
        for name in ('s3', 'gcs', 'azure'):
            example = OPERATORS / (name + '.yaml')
            self.assertTrue(example.is_file(), str(example))
            self.assertIn('DEPLOYMENT_STATE_CONF', example.read_text())
        for repository in ('monorepo-app-template', 'ruby-app-template'):
            self.assertFalse((WORKSPACE / repository / '.cloudopsworks/examples/backend').exists())

    def test_application_guidance_keeps_state_settings_out_of_the_repository(self):
        for repository in ('monorepo-app-template', 'ruby-app-template'):
            root = WORKSPACE / repository
            for path in ('README.yaml', 'AGENTS.md', '.cloudopsworks/examples/README.md'):
                text = (root / path).read_text()
                self.assertIn('DEPLOYMENT_STATE_CONF', text, str(root / path))
                self.assertIn('org/team', text, str(root / path))
            self.assertNotIn('`backend/*.yaml`', (root / '.cloudopsworks/examples/README.md').read_text())


if __name__ == '__main__':
    unittest.main()
