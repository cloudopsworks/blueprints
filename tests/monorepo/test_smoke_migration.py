"""Offline behavior checks for the maintained local migration journey."""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import smoke_migration


class MigrationBindingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/temporary/migration')
        self.path = self.root/'.cloudopsworks/cloudopsworks-ci.yaml'
        self.config = {'components': {name: {'targets': []} for name in
            ('api', 'web', 'worker', 'ruby-app', 'rails-app')}}
        self.plan = {'components': [
            {'id': name, 'targetIds': ['aws-eks'] if name in ('api', 'web', 'worker') else []}
            for name in self.config['components']],
            'targets': [{'id': 'aws-eks', 'environment': 'dev'}]}

    def invoke(self, plan=None):
        smoke = SimpleNamespace(yaml_write=Mock(), cli=Mock(),
            plan=Mock(return_value=(self.plan if plan is None else plan, self.root/'plan.json')))
        with patch.object(smoke_migration, 'yaml_read', return_value=self.config), \
                patch.object(smoke_migration, 'freeze_fixture'):
            result = smoke_migration.bind_and_plan(smoke, self.root, self.path)
        return smoke, result

    def test_existing_target_is_bound_and_verified_for_go_node_and_java(self):
        smoke, result = self.invoke()
        self.assertEqual(result, self.plan)
        for name in ('api', 'web', 'worker'):
            self.assertEqual(self.config['components'][name]['targets'], ['aws-eks'])
        for name in ('ruby-app', 'rails-app'):
            self.assertEqual(self.config['components'][name]['targets'], [])
        smoke.yaml_write.assert_called_once_with(self.path, self.config)
        smoke.cli.assert_called_once_with(self.root, 'validate')
        smoke.plan.assert_called_once_with(self.root)

    def test_missing_node_binding_in_actual_plan_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan['components'][1]['targetIds'] = []
        with self.assertRaisesRegex(AssertionError, 'planned component bindings differ'):
            self.invoke(plan)

    def test_changed_java_binding_in_actual_plan_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan['components'][2]['targetIds'] = ['another-target']
        with self.assertRaisesRegex(AssertionError, 'planned component bindings differ'):
            self.invoke(plan)

    def test_wrong_resolved_environment_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan['targets'][0]['environment'] = 'prod'
        with self.assertRaisesRegex(AssertionError, 'planned target environment differs'):
            self.invoke(plan)


class MigrationFixtureTests(unittest.TestCase):
    def test_final_sources_are_committed_before_immutable_head_planning(self):
        root = Path('/temporary/migration')
        smoke = SimpleNamespace(run=Mock(side_effect=[None,
            '.cloudopsworks/cloudopsworks-ci.yaml\ncomponents/rails-app/bin/rails\n', None, None]))
        smoke_migration.freeze_fixture(smoke, root)
        commands = [call.args[0] for call in smoke.run.call_args_list]
        self.assertEqual(commands[0], ['git', 'add', '.'])
        self.assertIn('commit', commands[2])
        self.assertEqual(commands[3], ['git', 'ls-files', '--error-unmatch',
            'components/rails-app/bin/rails'])

    def test_generated_build_products_are_not_committed(self):
        for product in ('components/rails-app/.bundle/vendor/gem.rb',
                'components/worker/target/app.jar', 'components/web/build/app.js',
                '.cloudopsworks/out/plan.json'):
            with self.subTest(product=product):
                smoke = SimpleNamespace(run=Mock(side_effect=[None, product+'\n']))
                with self.assertRaisesRegex(AssertionError, 'staged generated output'):
                    smoke_migration.freeze_fixture(smoke, Path('/temporary/migration'))
                self.assertEqual(smoke.run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
