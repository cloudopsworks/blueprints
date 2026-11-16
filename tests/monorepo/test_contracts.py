"""The exact shared corpus is consumed by Python and Tronador's Go validator."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import sys
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
SPEC = importlib.util.spec_from_file_location('contracts', ROOT / 'cd/monorepo/runtime/contracts.py')
contracts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contracts)
CORPUS = Path(__file__).with_name('contracts')


class SharedConformance(unittest.TestCase):
    def test_shared_corpus(self):
        cases = json.loads((CORPUS / 'cases.json').read_text())['cases']
        for case in cases:
            with self.subTest(case=case['id'], validation=case['validation']):
                stage = case['validation']
                if stage == 'structural':
                    def check():
                        contracts.validate_shape(contracts.load_record(CORPUS / case['payload']))
                else:
                    record = contracts.load_record(CORPUS / case['payload'])
                    # A semantic/context/artifact negative must pass earlier layers.
                    contracts.validate_shape(record)
                    if stage == 'semantic':
                        def check():
                            contracts.validate_record(record)
                    else:
                        contracts.validate_record(record)
                        context = copy.deepcopy(case.get('context', {}))
                        for key in ('plan', 'manifest'):
                            if key in context:
                                context[key] = contracts.load_record(CORPUS / context[key])
                        if stage == 'context':
                            def check():
                                contracts.validate_linked(record, context)
                        else:
                            def check():
                                contracts.validate_artifact(CORPUS / case['artifact'], record['mainArtifact'])
                if case['expected'] == 'reject':
                    with self.assertRaises(contracts.ContractError):
                        check()
                else:
                    check()

    def test_openapi_requires_trusted_validator_and_bounded_input(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(contracts.shutil, 'which', return_value=None):
            with self.assertRaises(contracts.ContractError) as error:
                contracts._validate_openapi(b'{}', 'openapi-yaml')
            self.assertEqual(error.exception.code, 'openapi-validator-unavailable')
        with self.assertRaises(contracts.ContractError):
            contracts._validate_openapi(b' ' * (contracts.MAX_DOCUMENT_BYTES + 1), 'openapi-json')
        with mock.patch.dict(os.environ, {'TRONADOR_TEST_BINARY':'relative/untrusted'}):
            with self.assertRaises(contracts.ContractError):
                contracts._validate_openapi(b'{}', 'openapi-json')

    def test_openapi_process_failure_does_not_leak_input_or_output(self):
        with mock.patch.dict(os.environ, {'TRONADOR_TEST_BINARY':'/trusted/tronador'}), mock.patch.object(contracts.Runner, 'run', side_effect=contracts.ExecutionError('secret parse output')) as run:
            with self.assertRaises(contracts.ContractError) as error:
                contracts._validate_openapi(b'{"secret":"payload"}', 'openapi-json')
            self.assertNotIn('secret', str(error.exception))
            self.assertEqual(run.call_args.args[0], ['/trusted/tronador', 'components', 'validate-openapi', '--format', 'openapi-json'])
            self.assertEqual(run.call_args.kwargs['input'], '{"secret":"payload"}')
            self.assertEqual(run.call_args.kwargs['cwd'], '/')

    def test_matching_plan_context_is_accepted(self):
        plan = contracts.load_record(CORPUS / 'valid/build-plan.json')
        result = contracts.load_record(CORPUS / 'valid/component-result.json')
        contracts.validate_linked(result, {'plan': plan})

    def test_verified_release_baseline_is_accepted(self):
        manifest = contracts.load_record(CORPUS / 'valid/release-manifest.json')
        proof = {'tag': manifest['tag'], 'draft': False,
                 'targetCommitish': manifest['headSha'], 'assetsVerified': True}
        contracts.validate_linked(manifest, {'githubRelease': proof})
        proof['assetsVerified'] = False
        with self.assertRaises(contracts.ContractError):
            contracts.validate_linked(manifest, {'githubRelease': proof})

    def test_safe_root_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(contracts.ContractError):
                contracts.rooted_path(root, 'link/file', must_exist=False)

    def test_schema_rejects_boolean_integer(self):
        record = contracts.load_record(CORPUS / 'valid/build-plan.json')
        record['repository']['id'] = True
        with self.assertRaises(contracts.ContractError):
            contracts.validate_record(record)

    def test_json_limit(self):
        with self.assertRaises(contracts.ContractError):
            contracts.load_record(b' ' * (contracts.MAX_DOCUMENT_BYTES + 1))


if __name__ == '__main__':
    unittest.main()
