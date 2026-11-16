"""Local exact-mode inventory and real CLI/native integration, never hosted code."""
import json
import hashlib
import zipfile
import os
import tempfile
from pathlib import Path
import subprocess
import unittest

BP = Path(__file__).resolve().parents[3]
INVENTORY = Path(__file__).with_name('native-mode-cases.yaml')
EXPECTED = {
 'aws-lambda': ['zip_digest_and_optional_alias', 'image_exact_private_ecr_digest'],
 'aws-beanstalk': ['owned_mock_apply', 'immutable_dockerrun_zip'],
 'aws-s3-static': ['owned_mock_apply'],
 'aws-apigateway-rest': ['owned_mock_apply', 'existing_owned_id_preserves_verified_name_description', 'native_json_openapi_exact_body'],
 'gcp-cloudrun': ['oci'],
 'gcp-appengine': ['standard_native', 'flex_native', 'flex_oci', 'standard_basic', 'standard_automatic'],
 'gcp-functions-gen2': ['http', 'pubsub', 'storage_finalize'],
 'gcp-storage-static': ['objectset', 'static_zip'],
 'gcp-apigateway': ['openapi', 'openapi_json'],
 'azure-containerapps': ['digest_revision'],
 'azure-appservice': ['linux_production_zip', 'linux_production_container', 'linux_staging_zip', 'linux_staging_container', 'windows_production_zip', 'windows_staging_zip'],
 'azure-functions': ['linux_production_zip', 'linux_production_container', 'linux_staging_zip', 'linux_staging_container', 'windows_production_zip', 'windows_staging_zip', 'flex_zip', 'dedicated_linux_production_zip', 'dedicated_linux_production_container', 'dedicated_linux_staging_zip', 'dedicated_linux_staging_container', 'dedicated_windows_production_zip', 'dedicated_windows_staging_zip', 'native_custom_handler'],
 'azure-blob-static': ['prefix_bound'],
 'azure-apim': ['api_exact_digest'],
 'kubernetes-component': ['eks_immutable_release', 'gke', 'aks'],
}


def yaml_data(path):
    return json.loads(subprocess.check_output(['yq', '-o=json', '-I=0', '.', str(path)], timeout=10))


class NativeModeInventory(unittest.TestCase):
    def test_exact_approved_modes_bind_current_yaml_roots_and_native_fixtures(self):
        self.assertTrue(INVENTORY.is_file(), 'Missing explicit native-mode-cases.yaml acceptance inventory')
        inventory = yaml_data(INVENTORY)
        self.assertEqual(set(inventory), {'schemaVersion', 'purpose', 'cases'})
        cases = inventory['cases']
        actual = [(row['root'], row['case']) for row in cases]
        expected = [(root, mode) for root, modes in EXPECTED.items() for mode in modes]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))
        catalog = yaml_data(BP/'terraform/monorepo/module-catalog.yaml')['modules']
        self.assertEqual(len({row['family'] for row in cases}), 17)
        for row in cases:
            with self.subTest(family=row['family'], mode=row['case']):
                self.assertEqual(set(row), {'family', 'root', 'case'})
                binding = catalog[row['family']]
                root = BP/binding['path']
                self.assertEqual(root.name, row['root'])
                self.assertTrue(binding['activationBlocked'], 'This local test never activates production')
                metadata = yaml_data(root/'inputs.yaml')
                self.assertTrue(metadata['activationBlocked'])
                native = list((root/'tests').glob('*.tftest.*'))
                self.assertEqual(len(native), 1)
                text = native[0].read_text()
                self.assertIn('"'+row['case']+'"', text)



class PrivatePayloadRemovalTests(unittest.TestCase):
    def test_only_existing_private_payloads_are_removed_once(self):
        from native_mode_fixture import remove_private_payloads
        with tempfile.TemporaryDirectory(prefix='native-expired-payload-') as temp:
            root = Path(temp).resolve()
            payload = root/'actual.zip'; payload.write_bytes(b'verified application bytes')
            missing = root/'unused-placeholder.zip'
            self.assertEqual(remove_private_payloads(root, [payload, missing, payload]), [payload])
            self.assertFalse(payload.exists())
            self.assertFalse(missing.exists())

    def test_artifact_reads_explicit_fixture_root_not_output_parent(self):
        from native_mode_fixture import NativeFixture
        with tempfile.TemporaryDirectory(prefix='native-source-root-') as temp:
            root = Path(temp).resolve(); source = root/'source'; source.mkdir()
            output = root/'output'; output.mkdir()
            (source/'package.zip').write_bytes(b'explicit native fixture bytes')
            variables = {'artifact':{'format':'zip', 'path':'package.zip'}}
            context = {'plan':{'headSha':'a'*40, 'version':'1.0.0', 'components':[{'package':{'kind':'archive'}}]}}
            descriptor, payload = NativeFixture.__new__(NativeFixture).artifact(variables, context, output, source)
            self.assertEqual(payload.read_bytes(), b'explicit native fixture bytes')
            self.assertEqual(payload.parent, output)
            self.assertEqual(descriptor['sizeBytes'], len(payload.read_bytes()))

    def test_external_payload_is_never_removed(self):
        from native_mode_fixture import remove_private_payloads
        with tempfile.TemporaryDirectory(prefix='native-expired-payload-') as temp:
            parent = Path(temp).resolve(); root = parent/'private'; root.mkdir()
            external = parent/'external.zip'; external.write_bytes(b'caller-owned')
            with self.assertRaises(AssertionError):
                remove_private_payloads(root, [external])
            self.assertEqual(external.read_bytes(), b'caller-owned')

    def test_private_symlink_is_not_followed_or_removed(self):
        from native_mode_fixture import remove_private_payloads
        with tempfile.TemporaryDirectory(prefix='native-expired-payload-') as temp:
            parent = Path(temp).resolve(); root = parent/'private'; root.mkdir()
            external = parent/'external.zip'; external.write_bytes(b'caller-owned')
            link = root/'linked.zip'; link.symlink_to(external)
            with self.assertRaises(AssertionError):
                remove_private_payloads(root, [link])
            self.assertTrue(link.is_symlink())
            self.assertEqual(external.read_bytes(), b'caller-owned')


class NativeModeTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_mode_fixture import NativeFixture, command
        binary = os.environ.get('TRONADOR_CLI')
        if not binary or not Path(binary).is_file():
            raise AssertionError('TRONADOR_CLI exact real binary required; modes never silently skip')
        if json.loads(command(['tofu', 'version', '-json']))['terraform_version'] != '1.11.4':
            raise AssertionError('Native plans require pinned OpenTofu1.11.4')
        cls.temporary = tempfile.TemporaryDirectory(prefix='composite-native-modes-')
        cls.fixture = NativeFixture(Path(cls.temporary.name).resolve(), binary, yaml_data(INVENTORY)['cases'])
        cls.results = []
        cls.binary_digest = 'sha256:'+hashlib.sha256(Path(binary).read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('NATIVE_MODE_RESULTS'):
            path = Path(os.environ['NATIVE_MODE_RESULTS'])
            path = path.with_name(path.stem+'-'+cls.__name__+path.suffix)
            path.write_text(json.dumps(cls.results, indent=2)+'\n')
        cls.temporary.cleanup()

    def prepare_forward(self, row, result, stage):
        fixture = self.fixture
        native, original, plans = fixture.harvest(row['root'])
        variables = {key: item['value'] for key, item in plans[row['case']]['variables'].items()}
        binding = fixture.catalog[row['family']]
        result.update(fixture='passed', binaryDigest=self.binary_digest, nativeVersion='1.11.4',
            moduleRevision=binding['revision'], providerLockDigest=binding['providerLockDigest'],
            actualProviderLockDigest='sha256:'+hashlib.sha256((native/'.terraform.lock.hcl').read_bytes()).hexdigest())
        self.assertEqual(result['actualProviderLockDigest'], result['providerLockDigest'])
        context = fixture.context(variables, row)
        apply = fixture.cli(['operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api'], context)
        self.assertEqual(apply['inputs']['resource'], apply['stateHandle']['resourceIdentity'])
        result['forwardOperation'] = 'passed'
        directory = fixture.root/(stage+'-'+row['family']+'-'+row['case']); directory.mkdir(mode=0o700)
        descriptor, payload = fixture.artifact(variables, context, directory, native)
        descriptor_path = fixture.private(directory, 'artifact.json', descriptor)
        if payload:
            fixture.cli(['artifacts','verify','--mode','payload','--descriptor',str(descriptor_path),'--payload',str(payload)])
        result['forwardArtifact'] = 'passed'
        derived = {'component':context['plan']['components'][0]}
        metadata = yaml_data(native/'inputs.yaml')
        if 'kubeconfig_path' in metadata['variables']:
            kube = directory/'offline-kubeconfig'
            kube.write_text('apiVersion: v1\nkind: Config\nclusters:\n- name: offline\n  cluster:\n    server: https://127.0.0.1:9\n    insecure-skip-tls-verify: true\ncontexts:\n- name: offline\n  context:\n    cluster: offline\n    user: offline\ncurrent-context: offline\nusers:\n- name: offline\n  user:\n    token: offline-not-a-credential\n')
            kube.chmod(0o600)
            derived.update(kubeconfig_path=str(kube), readiness_seconds=60)
        if 'resolved_api' in metadata['variables']:
            derived['resolved_api'] = variables.get('resolved_api')
        output = directory/'forward-rendered'; output.mkdir(mode=0o700)
        args = ['operations','render','--plan',str(fixture.private(directory,'apply.json',apply)),
            '--module-root',str(BP/'terraform/monorepo/modules'/row['root']), '--output',str(output),
            '--artifact',str(descriptor_path),'--derived',str(fixture.private(directory,'derived.json',derived))]
        if payload:
            args.extend(['--payload',str(payload)])
        rendered = fixture.cli(args)
        self.assertFalse(rendered['evaluationOnly'])
        values = json.loads(Path(rendered['valuesPath']).read_text())
        self.assertEqual(values['owner_digest'], apply['stateHandleDigest'])
        self.assertEqual(values['artifact']['digest'], descriptor['digest'])
        if 'release_name' in values:
            self.assertEqual(values['release_name'], apply['stateHandle']['releaseName'])
        if context['plan']['components'][0]['package']['kind'] == 'static':
            self.assertTrue(values['artifact']['files'], 'Static forward requires the verified nonempty file set')
            with zipfile.ZipFile(payload) as archive:
                self.assertEqual([item['key'] for item in values['artifact']['files']], sorted(archive.namelist()))
                for item in values['artifact']['files']:
                    self.assertEqual(Path(item['path']).read_bytes(), archive.read(item['key']))
        result['forwardRender'] = 'passed'
        if 'package_read_sas' in variables:
            # Explicit native protected-secret fixture, never acquired by the renderer.
            values['package_read_sas'] = variables['package_read_sas']
        return native, original, plans[row['case']], context, apply, descriptor, payload, derived, values, directory

    def expected_addresses(self, harvested):
        addresses = {item['address'] for item in harvested.get('resource_changes', []) if item['mode'] == 'managed'}
        self.assertTrue(addresses, 'Populated native fixture must declare owned managed resources')
        return addresses


class ActualModeForwardRender(NativeModeTestBase):
    def run_forward(self, row):
        result = dict(row, native='not-run')
        try:
            native, original, harvested, context, apply, descriptor, payload, derived, values, directory = self.prepare_forward(row, result, 'forward')
            view = self.fixture.native_run(native, original, row, values)
            changes = {item['address']:item for item in view.get('resource_changes', []) if item['mode'] == 'managed'}
            expected = self.expected_addresses(harvested)
            self.assertEqual(set(changes), expected, 'Native rendered apply must contain every exact expected owned object')
            self.assertTrue(all(item['change']['actions'] == ['create'] for item in changes.values()))
            self.assertFalse(any(item['change'].get('importing') for item in changes.values()))
            self.assertEqual(view['variables']['artifact']['value'], values['artifact'])
            result.update(native='passed', expectedOwnedAddresses=sorted(expected), actualOwnedAddresses=sorted(changes),
                expectedOwnedCount=len(expected), actualOwnedCount=len(changes))
        except Exception as error:
            result['failure'] = str(error)
            raise
        finally:
            self.results.append(result)


class ActualModeHistoricalRender(NativeModeTestBase):
    def run_historical(self, row):
        from native_mode_fixture import native_state, remove_private_payloads
        result = dict(row, priorState='not-run', render='not-run', nativeDestroy='not-run')
        try:
            fixture = self.fixture
            native, original, harvested, context, apply, descriptor, payload, derived, prior_values, directory = self.prepare_forward(row, result, 'history')
            # Prior state comes from the actual forward renderer, not native fixture values
            # with an owner annotation pasted on. In particular release_name is the handle's.
            view = fixture.native_run(native, original, row, prior_values, apply=True)
            state = native_state(view)
            managed = {item['address']:item for item in view['values']['root_module']['resources'] if item['mode'] == 'managed'}
            expected = self.expected_addresses(harvested)
            self.assertEqual(set(managed), expected)
            if row['root'] == 'kubernetes-component':
                release = managed['helm_release.component']['values']
                self.assertEqual(release['name'], apply['stateHandle']['releaseName'])
                self.assertEqual(release['namespace'], apply['stateHandle']['resourceIdentity']['namespace'])
                self.assertEqual(release['description'], apply['stateHandleDigest'])
            result.update(priorState='passed', identityAlignedForwardValues=True,
                priorStateDigest='sha256:'+hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(),
                expectedOwnedAddresses=sorted(expected), expectedOwnedCount=len(expected))
            artifact = prior_values['artifact']
            candidates = [payload, artifact.get('path')]+[item['path'] for item in artifact.get('files', [])]
            removed = remove_private_payloads(fixture.root, candidates)
            self.assertTrue(all(not path.exists() for path in removed))
            if descriptor['format'] != 'oci':
                self.assertTrue(removed, 'Archive/API prior payloads must actually expire before recovery')
            result['originalPayloadsRemoved'] = len(removed)
            context['historicalHandle'] = apply['stateHandle']
            destroy = fixture.cli(['operations','plan','--operation','destroy','--environment','prod','--target','prod-run','--component','api'], context)
            self.assertIsNone(destroy['inputs'], 'Recovery must not invent forward artifact inputs')
            result['operation'] = 'passed'
            output = directory/'historical-rendered'; output.mkdir(mode=0o700)
            rendered = fixture.cli(['operations','render','--plan',str(fixture.private(directory,'destroy.json',destroy)),
                '--module-root',str(BP/'terraform/monorepo/modules'/row['root']), '--output',str(output),
                '--historical-config',str(fixture.private(directory,'historical.yaml',context)),
                '--prior-state',str(fixture.private(directory,'prior.json',state)),
                '--derived',str(fixture.private(directory,'historical-derived.json',derived))])
            self.assertTrue(rendered['evaluationOnly'])
            self.assertEqual(rendered['operation'], 'destroy')
            self.assertTrue(all(not path.exists() for path in removed))
            values = json.loads(Path(rendered['valuesPath']).read_text())
            self.assertEqual(values['owner_digest'], apply['stateHandleDigest'])
            if descriptor['format'] == 'oci':
                evaluation = values['artifact']
                self.assertEqual(evaluation['format'], 'oci')
                self.assertEqual(evaluation['imageReference'], '')
                self.assertEqual(evaluation['digest'], '')
                # Some native roots omit unused files/path fields in their projection.
                self.assertEqual(evaluation.get('files', []), [])
                self.assertIsNone(evaluation.get('path'))
                output_files = sorted(path.name for path in output.iterdir())
                self.assertEqual(output_files, [Path(rendered['valuesPath']).name],
                    'OCI destroy evaluation must emit native values only, no payload/image bytes')
                result['ociEvaluation'] = dict(evaluation, outputFiles=output_files)
            result['render'] = 'passed'
            saved, plan_digest = fixture.saved_destroy(row, directory, values, state)
            changes = {item['address']:item['change']['actions'] for item in saved.get('resource_changes', []) if item['mode'] == 'managed'}
            self.assertEqual(changes, {address:['delete'] for address in expected},
                'Saved native recovery plan must delete every owned object and mutate no external parent')
            self.assertFalse(any(item['change'].get('importing') for item in saved.get('resource_changes', [])))
            self.assertTrue(all(not path.exists() for path in removed), 'Native destroy must not recover original application bytes')
            result.update(nativeDestroy='passed', savedPlanDigest=plan_digest, deleteActions=changes,
                actualDeleteCount=len(changes))
        except Exception as error:
            result['failure'] = str(error)
            raise
        finally:
            self.results.append(result)


def mode_test(row, historical=False):
    def check(self):
        if historical: self.run_historical(row)
        else: self.run_forward(row)
    check.__doc__ = f"{row['family']} {row['case']}: " + ('real forward identities -> native prior Apply -> expired payload -> actual saved delete-only plan.' if historical else 'actual Go apply plan/render -> native mock plan.')
    return check


# Test-only explicit inventory creates one independently reported test per mode/stage.
if INVENTORY.is_file():
    for case in yaml_data(INVENTORY)['cases']:
        name = 'test_'+case['family'].replace('-','_')+'__'+case['case']
        setattr(ActualModeForwardRender, name, mode_test(case))
        setattr(ActualModeHistoricalRender, name, mode_test(case, historical=True))


if __name__ == '__main__':
    unittest.main()

