"""Normal production entrypoint composition and fixed workflow security graph."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
import normal_entry as normal
from contracts import ContractError


class NormalEntryTests(unittest.TestCase):
    def test_selection_finishes_before_credentials_and_keeps_backend_distinct(self):
        calls=[]
        def choose(*args,**kwargs):
            calls.append((args,kwargs));return {'workload':{'provider':'gcp','authRef':'app'},
                'backend':{'provider':'aws','authRef':'state','settings':{}},'historicalHandle':None}
        prepared=SimpleNamespace(select_bindings=choose)
        values=normal.select(prepared,'dev','api','native YAML',{'auth':'protected'},'42')
        self.assertEqual(values,{'workload-provider':'gcp','workload-ref':'app','backend-provider':'aws','backend-ref':'state','same-binding':'false'})
        self.assertEqual(calls[0][1],{'automation_id':'42'})
        self.assertNotIn('native YAML',str(values));self.assertNotIn('protected',str(values))
    def test_complete_matrix_ignores_build_selection_and_output_injection(self):
        prepared=SimpleNamespace(manifest={'targets':[{'id':'dev'},{'id':'prod'}],
            'components':[{'componentId':'api','targetIds':['dev','prod']},{'componentId':'worker','targetIds':['dev']}]})
        self.assertEqual(len(normal.matrix(prepared)['include']),3)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'output'
            normal.output({'matrix':json.dumps(normal.matrix(prepared))},path)
            with self.assertRaises(ContractError):normal.output({'bad':'a\nSECRET=sentinel'},path)
            self.assertNotIn('sentinel',path.read_text())
    def test_preflight_composes_native_and_actual_authorization_without_apply(self):
        prepared=SimpleNamespace(authorize=lambda request,resolved:{'actual':'operation'})
        emitted=[]
        with patch.object(normal,'resolve_binding',return_value=({'request':1},{'resolved':1},{},object())), \
             patch('preflight_barrier.binding_marker',return_value='closed marker') as marker:
            result=normal.preflight(prepared,object(),'dev','api',{},'private',emit=lambda line,**kw:emitted.append(line))
        self.assertEqual(result,{'actual':'operation'});self.assertEqual(emitted,['closed marker'])
        marker.assert_called_once_with(prepared,{'request':1},{'resolved':1},result)
    def test_branch_stage_does_not_publish_and_exact_version_tag_only(self):
        p=SimpleNamespace(current_host={'event':'push','ref':'refs/heads/develop'},manifest={'tag':'v1.2.3'})
        self.assertFalse(normal.public_release_eligible(p))
        with self.assertRaises(ContractError):normal.publish(p,None,None,None)
        p.current_host['ref']='refs/tags/v1.2.3';self.assertTrue(normal.public_release_eligible(p))
        p.current_host['ref']='refs/tags/v1.2.4';self.assertFalse(normal.public_release_eligible(p))
        p.current_host.update(event='workflow_dispatch',ref='refs/tags/v1.2.3');self.assertFalse(normal.public_release_eligible(p))

    def test_selected_cloud_runner_preserves_readiness_timeout_budget(self):
        from protected_runtime import CloudExecutor
        runner=normal.NativeRunner(timeout=600,inherit_environment=False)
        bounded=CloudExecutor(runner,{'PATH':'/trusted/bin'}).bounded(12)
        self.assertEqual(bounded.executor.timeout,12)
        self.assertFalse(bounded.executor.inherit_environment)
        self.assertEqual(bounded.environment,{'PATH':'/trusted/bin'})

    def test_normal_and_manual_share_one_whole_graph_serialization_owner(self):
        group='group: cloudopsworks-state-${{ github.repository_id }}'
        for name in ('main-build','operation','manual-apply'):
            source=(ROOT/f'.github/workflows/monorepo-{name}.yml').read_text()
            prefix,jobs=source.split('jobs:',1)
            self.assertEqual(prefix.count('concurrency:'),1)
            self.assertIn(group,prefix);self.assertIn('cancel-in-progress: false',prefix)
            self.assertNotIn('concurrency:',jobs,'one owner, not per-job lock gaps or nested self-lock')
        fixture=json.loads((ROOT/'tests/monorepo/fixtures/revision_callers.json').read_text())
        for caller in fixture['callers']:
            if caller['reusable'].endswith(('monorepo-main-build.yml','monorepo-operation.yml','monorepo-manual-apply.yml')):
                self.assertNotIn('concurrency',caller)

    def test_manual_apply_publication_and_scanner_caps_do_not_elevate_recovery(self):
        fixture=json.loads((ROOT/'tests/monorepo/fixtures/revision_callers.json').read_text())
        rows={r['caller']:r for r in fixture['callers']}
        apply=rows['deploy.yml']
        self.assertTrue(apply['reusable'].endswith('monorepo-manual-apply.yml'))
        self.assertEqual(apply['permissions']['packages'],'write')
        scanners={'SONARQUBE_TOKEN','SNYK_TOKEN','SEMGREP_TOKEN','DEPENDENCYTRACK_TOKEN'}
        self.assertTrue(scanners <= set(apply['secrets']))
        source=(ROOT/'.github/workflows/monorepo-manual-apply.yml').read_text()
        self.assertIn('packages: write',source)
        self.assertIn('needs: [source, scan]',source)
        self.assertIn('scan_entry.py barrier',source)
        recovery=(ROOT/'.github/workflows/monorepo-operation.yml').read_text()
        self.assertNotIn('packages: write',recovery)
        self.assertNotIn('scan_entry.py',recovery)
        for name in ('environment-destroy.yml','environment-unlock.yml'):
            self.assertEqual(rows[name]['permissions']['packages'],'read')
            self.assertFalse(scanners & set(rows[name]['secrets']))

    def test_backend_configuration_is_org_variable_primary_not_repository_file(self):
        expression='${{ vars.DEPLOYMENT_STATE_CONF || secrets.DEPLOYMENT_STATE_CONF }}'
        for name in ('main-build','manual-apply','operation'):
            source=(ROOT/f'.github/workflows/monorepo-{name}.yml').read_text()
            bindings=[line.strip() for line in source.splitlines() if line.strip().startswith('DEPLOYMENT_STATE_CONF: ${{')]
            self.assertTrue(bindings,name)
            self.assertTrue(all(line=='DEPLOYMENT_STATE_CONF: '+expression for line in bindings),name)
        # The runtime accepts only the selected protected native YAML text. A
        # repository-local file is never a second state authority.
        seen=[]
        prepared=SimpleNamespace(select_bindings=lambda target,component,backend,settings,**kw:
            (seen.append(backend) or {'workload':{'provider':'aws','authRef':'app'},
                'backend':{'provider':'aws','authRef':'state','settings':{}},'historicalHandle':None}))
        with tempfile.TemporaryDirectory() as directory:
            decoy=Path(directory)/'.cloudopsworks/backend.yaml';decoy.parent.mkdir()
            decoy.write_text('s3: {bucket: attacker, auth_ref: attacker}')
            with patch('pathlib.Path.read_text',side_effect=AssertionError('repository backend must not be read')):
                normal.select(prepared,'dev','api','s3: {bucket: protected, auth_ref: state}',{},'42')
        self.assertEqual(seen,['s3: {bucket: protected, auth_ref: state}'])

    def test_workflow_actual_global_barrier_and_pair_order(self):
        source=(ROOT/'.github/workflows/monorepo-main-build.yml').read_text()
        self.assertIn('name: monorepo-preflight-${{ matrix.target }}-${{ matrix.component }}',source)
        self.assertIn('name: monorepo-preflight-barrier',source)
        self.assertIn('needs: [stage, scan, deployment-context, preflight-barrier]',source)
        for block in source.split('  preflight:',1)[1].split('  preflight-barrier:',1)[:1]+source.split('  apply:',1)[1:]:
            self.assertLess(block.index('normal_entry.py configure'),block.index('context-name: workload'))
            self.assertLess(block.index('tg_version:'),block.index('context-name: workload'))
            self.assertIn('context-name: backend',block)
            self.assertIn("if: steps.context.outputs.same-binding != 'true'",block)
        self.assertNotIn('path: ${{ runner.temp }}',source)

if __name__=='__main__':unittest.main()
