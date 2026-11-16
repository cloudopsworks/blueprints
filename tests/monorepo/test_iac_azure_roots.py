"""Pinned Azure roots: schema/mode/mock proof, deliberately not cloud execution."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'terraform/monorepo/modules'
NAMES = ('azure-containerapps', 'azure-appservice', 'azure-functions', 'azure-blob-static', 'azure-apim')
FIXTURES = ROOT / 'tests/monorepo/fixtures/iac_capabilities'


class AzureRootTests(unittest.TestCase):
    def test_selected_provider_validation_and_mock_modes(self):
        tofu = shutil.which('tofu')
        self.assertIsNotNone(tofu, 'Exact OpenTofu is a prerequisite, not a skipped success')
        version = json.loads(subprocess.run([tofu, 'version', '-json'], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(version['terraform_version'], '1.11.4')
        plugins = Path(os.environ.get('TOFU_PLUGIN_DIR', ROOT / 'terraform/monorepo/capabilities/.terraform/providers'))
        self.assertTrue(plugins.is_dir())
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ARM_', 'AZURE_', 'TF_VAR_', 'TF_CLI_', 'TF_LOG'))}
        env.update(HTTPS_PROXY='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9', NO_PROXY='')
        with tempfile.TemporaryDirectory(prefix='azure-root-tests-') as temporary:
            for name in NAMES:
                with self.subTest(root=name):
                    destination = Path(temporary) / name
                    shutil.copytree(MODULES / name, destination, ignore=shutil.ignore_patterns('.terraform', '*.tfstate*'))
                    for args in (
                        ('fmt', '-check', '-recursive'),
                        ('init', '-backend=false', '-input=false', '-lockfile=readonly', f'-plugin-dir={plugins.resolve()}'),
                        ('validate', '-no-color'),
                        ('test', '-no-color'),
                    ):
                        result = subprocess.run([tofu, *args], cwd=destination, env=env, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, f'{name} {args}:\n{result.stdout}\n{result.stderr}')
                    self.assertIn('0 failed', result.stdout)
                    self.assertIn('owned_mock_apply', result.stdout)
                    provider = json.loads(subprocess.run([tofu, 'providers', 'schema', '-json'], cwd=destination, env=env, capture_output=True, text=True, check=True).stdout)
                    azure = provider['provider_schemas']['registry.opentofu.org/hashicorp/azurerm']
                    for kind in json.loads((destination / 'inputs.json').read_text())['ownedResourceTypes']:
                        self.assertIn(kind, azure['resource_schemas'])

    def test_owned_addresses_and_no_landing_zone_or_shell_mutations(self):
        forbidden = {'azurerm_resource_group', 'azurerm_storage_account', 'azurerm_storage_container', 'azurerm_service_plan', 'azurerm_user_assigned_identity', 'azurerm_role_assignment', 'azurerm_container_app_environment', 'azurerm_api_management'}
        for name in NAMES:
            with self.subTest(root=name):
                directory = MODULES / name
                metadata = json.loads((directory / 'inputs.json').read_text())
                source = '\n'.join(p.read_text() for p in directory.glob('*.tf'))
                resources = re.findall(r'resource "([^"]+)" "([^"]+)"', source)
                self.assertEqual(set(metadata['ownedResourceTypes']), {kind for kind, _ in resources})
                self.assertFalse(forbidden & set(metadata['ownedResourceTypes']))
                for kind, label in resources:
                    self.assertTrue(any(address.split('[')[0] == f'{kind}.{label}' for address in metadata['ownedResourceAddresses']))
                self.assertNotRegex(source, r'local-exec|remote-exec|provisioner|data "(?:external|http)"|yamldecode|zip_deploy_file|import\s*\{\s*to\s*=')
                self.assertIn('version = "= 4.66.0"', (directory / 'versions.tf').read_text())
                self.assertIn('resource_provider_registrations = "none"', (directory / 'versions.tf').read_text())
                self.assertTrue(metadata['activationBlocked'])
                self.assertNotIn('/Users/', (directory / 'tests/roots.tftest.hcl').read_text())

    def test_package_operations_are_sensitive_fixed_children(self):
        for name in ('azure-appservice', 'azure-functions'):
            directory = MODULES / name
            source = (directory / 'main.tf').read_text()
            metadata = json.loads((directory / 'inputs.json').read_text())
            self.assertNotIn('package_read_sas', metadata['variables'])
            self.assertEqual(metadata['sensitiveInputs'], ['package_read_sas'])
            self.assertRegex(source, r'variable "package_read_sas"\s*\{[^}]*sensitive\s*=\s*true')
            self.assertRegex(source, r'packageUri\s*=\s*\{\s*type\s*=\s*"securestring"')
            self.assertIn('Microsoft.Web/sites/extensions', source)
            self.assertIn('Microsoft.Web/sites/slots/extensions', source)
            self.assertIn('delete_nested_items_during_deletion = false', (directory / 'versions.tf').read_text())
            self.assertIn('filesha256(var.artifact.path) == local.digest', source)
            self.assertIn('${local.digest}/${local.package_basename}', source)
            self.assertNotIn('package_read_sas', source[source.index('output "owned_ids"'):])
            self.assertIn('data "azurerm_linux_', source)
            self.assertIn('parent_linux', source)
            digest = hashlib.sha256((directory / 'tests/package.zip').read_bytes()).hexdigest()
            self.assertIn(digest, (directory / 'tests/roots.tftest.hcl').read_text())
        source = (MODULES / 'azure-functions/main.tf').read_text()
        self.assertIn('released-package.zip', source)
        self.assertIn("/onedeploy", source)
        self.assertRegex(source, r'remoteBuild\s*=\s*false')
        self.assertIn('image_name', source)
        self.assertIn('@sha256', source)

    def test_changed_zip_at_same_transport_path_changes_object_identity(self):
        """Same filename, different exact bytes: only digest-addressed objects change."""
        tofu = shutil.which('tofu')
        self.assertIsNotNone(tofu)
        plugins = (ROOT / 'terraform/monorepo/capabilities/.terraform/providers').resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ARM_', 'AZURE_', 'TF_VAR_', 'TF_CLI_', 'TF_LOG'))}
        env.update(HTTPS_PROXY='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9', NO_PROXY='')
        with tempfile.TemporaryDirectory(prefix='azure-package-same-path-') as temporary:
            for name in ('azure-appservice', 'azure-functions'):
                directory = Path(temporary) / name
                shutil.copytree(MODULES / name, directory, ignore=shutil.ignore_patterns('.terraform', '*.tfstate*'))
                result = subprocess.run([tofu, 'init', '-backend=false', '-input=false', '-lockfile=readonly', f'-plugin-dir={plugins}'], cwd=directory, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                original = (directory / 'tests/roots.tftest.hcl').read_text()
                variables = {}
                for line in original.split('run "owned_mock_apply"', 1)[1].split('run ', 1)[0].splitlines():
                    match = re.match(r'\s*(resource|configuration|workload|artifact|owner_digest|package_read_sas)\s*=\s*(.*)', line)
                    if match:
                        variables[match[1]] = json.loads(match[2])
                path = directory / variables['artifact']['path']
                names = []
                for content in (path.read_bytes(), (directory / 'tests/changed-package.zip').read_bytes()):
                    path.write_bytes(content)
                    digest = hashlib.sha256(content).hexdigest()
                    variables['artifact']['digest'] = 'sha256:' + digest
                    test = original.split('run "owned_mock_apply"', 1)[0] + '\nrun "same_path" {\n command=plan\n variables {\n' + ''.join(k + '=' + json.dumps(v) + '\n' for k, v in variables.items()) + '}\n}\n'
                    (directory / 'tests/roots.tftest.hcl').write_text(test)
                    result = subprocess.run([tofu, 'test', '-json', '-verbose'], cwd=directory, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    events = [json.loads(line) for line in result.stdout.splitlines()]
                    plan = next(event['test_plan'] for event in events if event.get('type') == 'test_plan')
                    resource = next(item for item in plan['resource_changes'] if item['address'] == 'azurerm_storage_blob.package[0]')
                    object_name = resource['change']['after']['name']
                    self.assertEqual(object_name, 'component/' + digest + '/main.zip')
                    names.append(object_name)
                self.assertNotEqual(*names)

    def test_no_listkeys_and_conservative_apim_delete_boundary(self):
        report = json.loads((FIXTURES / 'azure_roots_source_operations.json').read_text())
        captured = {record['path']: record['content'] for record in json.loads((FIXTURES / 'azure_source.json').read_text())['sources']}
        additional = report['additionalSources']
        for record in additional.values():
            self.assertEqual(hashlib.sha256(record['content'].encode()).hexdigest(), record['sha256'])
        self.assertIn('ListKeys', additional['storage_account_data_source']['content'])
        self.assertNotIn('ListKeys', additional['resources_data_source']['content'])
        self.assertIn('ListByResourceGroup', additional['resources_data_source']['content'])
        for name in ('azure-appservice', 'azure-functions', 'azure-blob-static'):
            source = (MODULES / name / 'main.tf').read_text()
            self.assertNotIn('data "azurerm_storage_account"', source)
            self.assertIn('data "azurerm_resources"', source)
            self.assertIn('== 1', source)
            self.assertIn('storage_use_azuread', (MODULES / name / 'versions.tf').read_text())
        function_source = (MODULES / 'azure-functions/main.tf').read_text()
        self.assertEqual(len(re.findall(r'storage_uses_managed_identity\s*=\s*true', function_source)), 4)
        self.assertNotIn('storage_account_access_key', function_source)
        for os_name in ('linux', 'windows'):
            for suffix, value in (('', 'functionApp'), ('_slot', 'functionAppSlot')):
                content = captured[f'appservice_{os_name}_function_app{suffix}_resource.go']
                self.assertNotIn('ListKeys', content)
                self.assertIn(f'storageString := {value}.StorageAccountName', content)
                self.assertIn(f'if !{value}.StorageUsesMSI {{', content)
                self.assertIn('if !state.StorageUsesMSI {', content)
                self.assertRegex(content, r'case "AzureWebJobsStorage__accountName":\s*m.StorageUsesMSI = true\s*m.StorageAccountName = v')
        sdk = additional['apim_sdk_delete']['content']
        self.assertIn('return DeleteOperationOptions{}', sdk)
        self.assertIn('if o.DeleteRevisions != nil', sdk)
        self.assertIn('api.DefaultDeleteOperationOptions()', captured['apimanagement_api_management_api_resource.go'])
        self.assertIn('whole API identity', report['apimDeleteBoundary']['serverDefault'])

    def test_source_operation_provenance_is_exact_and_honest(self):
        source = json.loads((FIXTURES / 'azure_source.json').read_text())
        report = json.loads((FIXTURES / 'azure_roots_source_operations.json').read_text())
        self.assertEqual(report['providerVersion'], '4.66.0')
        self.assertEqual(report['sourceCommit'], source['commit'])
        self.assertIn('not cloud execution', report['proofLevel'])
        original = {record['path']: record for record in source['sources']}
        for name, record in report['sources'].items():
            self.assertEqual(hashlib.sha256(original[name]['content'].encode()).hexdigest(), record['sha256'])
            self.assertEqual(record['url'], original[name]['url'])
            for function in record['functions']:
                self.assertEqual(original[name]['content'].splitlines()[function['line'] - 1], function['signature'])
        self.assertEqual(set(report['rootMechanisms']), set(NAMES))
        self.assertTrue(any('Mock provider' in value for value in report['limitations']))
        self.assertIn('delete_nested_items_during_deletion=false', report['destroyBoundary'])


if __name__ == '__main__':
    unittest.main()
