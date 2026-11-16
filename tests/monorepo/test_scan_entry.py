import diagnostic_support
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import load_record
from scan_entry import ScanRunner, outputs, scan, barrier
from test_release import fixture


class ScanEntryTests(unittest.TestCase):
    def prepared(self):
        data={'plan':fixture('build-plan'),'manifest':fixture('release-manifest'),
            'resolved':{'scanners':load_record(Path(__file__).with_name('fixtures')/'operations/scanners.json')},
            'lifecycle':{'protectedEnvironment':'develop/dev'},
            'stage':{'runId':'12','runAttempt':'1','artifactId':'99','archiveDigest':'sha256:'+'a'*64}}
        # Existing golden is the configuration object, not a document wrapper.
        for key in data['resolved']['scanners']:
            if isinstance(data['resolved']['scanners'][key],bool):data['resolved']['scanners'][key]=False
        return SimpleNamespace(inspect=lambda:copy.deepcopy(data),host={'event':'workflow_run'}),data

    def test_disabled_barrier_has_exact_allcomponent_coverage_current_digest_and_marker(self):
        prepared,data=self.prepared();lines=[]
        with tempfile.TemporaryDirectory() as directory:
            result=scan(prepared,None,ScanRunner(inherit_environment=False),directory,{},
                emit=lambda line,**kwargs:lines.append(line))
        self.assertEqual(len(result),5*len(data['plan']['components']))
        self.assertEqual({r['status'] for r in result},{'disabled'})
        self.assertEqual(len(lines),1)
        self.assertTrue(lines[0].startswith('CLOUDOPSWORKS_SCAN_V1 '))
        marker=json.loads(lines[0].split(' ',1)[1]);self.assertEqual(marker['stageArtifactId'],'99')

    def test_inspection_outputs_are_typed_machine_data_and_source_plan_not_new_authority(self):
        prepared,data=self.prepared()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);values=outputs(prepared,root/'plan',root/'out')
            self.assertEqual(values['environment'],'develop/dev')
            self.assertEqual(load_record(root/'plan'),data['plan'])
            self.assertIn('sonarqube=false',(root/'out').read_text())

    def test_carried_no_build_selection_still_installs_active_toolchains(self):
        from workflow import tools
        plan=fixture('build-plan');plan.update(buildSelection=[],matrix={'include':[]},buildNoop=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan';path.write_text(json.dumps(plan));found={}
            with patch('workflow.output',side_effect=lambda key,value:found.update({key:value})):
                tools(SimpleNamespace(plan=path,component='api',scan_component=True))
            self.assertEqual(found['go'],'1.26.7')

    def test_unrelated_exact_tool_versions_are_isolated_per_active_carried_worker(self):
        from workflow import tools
        plan=fixture('build-plan');plan.update(buildSelection=[],matrix={'include':[]},buildNoop=True)
        first=plan['components'][0];first['targetIds']=[]
        other=copy.deepcopy(first);other.update(id='web',path='components/web')
        other['toolchains'][0].update(version='1.25.1',components=['web'])
        plan['components'].append(other)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan';path.write_text(json.dumps(plan))
            for ident,version in [('api','1.26.7'),('web','1.25.1')]:
                found={}
                with patch('workflow.output',side_effect=lambda key,value:found.update({key:value})):
                    tools(SimpleNamespace(plan=path,component=ident,scan_component=True))
                self.assertEqual(found['go'],version)

    def test_barrier_binds_exact_completed_workers_not_self_declared_required_or_old_stage(self):
        prepared,data=self.prepared()
        prepared.current_host={'workflowRef':'example/app/.github/workflows/main-build.yml@refs/heads/develop',
            'runId':'12','runAttempt':'1'}
        lines=[]
        with tempfile.TemporaryDirectory() as directory:
            result=scan(prepared,None,ScanRunner(inherit_environment=False),directory,{},component_id='api',
                emit=lambda line,**kwargs:lines.append(line))
        class Host:
            def __init__(self):self.logs=lines[0].encode();self.name='lifecycle / monorepo-component-scan-api'
            def repo(self,method,path,**kwargs):
                if path.endswith('/logs'):return self.logs
                return {'jobs':[{'id':9,'run_id':12,'run_attempt':1,'name':self.name,'status':'completed','conclusion':'success'}]}
        github=Host();markers=[]
        self.assertEqual(barrier(prepared,github,emit=lambda line,**kwargs:markers.append(line)),result)
        self.assertEqual(len(markers),1)
        for mutation in ('stage','required','duplicate','job'):
            github=Host()
            record=json.loads(lines[0].split(' ',1)[1])
            if mutation=='stage':record['stage']['artifactId']='100'
            elif mutation=='required':record['results'][0]['required']=True
            elif mutation=='duplicate':record['results'].append(record['results'][0])
            else:github.name='attacker / monorepo-component-scan-api'
            github.logs=('CLOUDOPSWORKS_COMPONENT_SCAN_V1 '+json.dumps(record)).encode()
            with self.subTest(mutation=mutation),self.assertRaises(Exception):barrier(prepared,github)

    def test_native_scanner_process_keeps_path_but_not_host_tokens(self):
        with patch.dict(os.environ,{'GH_TOKEN':'secret-sentinel','PATH':os.environ['PATH']}):
            result=ScanRunner(inherit_environment=False).run([sys.executable,'-c',
                'import os; assert "GH_TOKEN" not in os.environ; assert os.environ["PATH"]; print("ok")'])
        self.assertEqual(result.stdout.strip(),'ok')

    def test_private_carried_oci_is_verified_before_token_isolated_trivy(self):
        prepared,data=self.prepared();data['resolved']['scanners']['trivyEnabled']=True
        artifact=fixture('oci-image-valid')['mainArtifact']
        artifact['location']={'kind':'oci','reference':'ghcr.io/example/app/api@'+artifact['digest']}
        data['manifest']['components'][0]['mainArtifact']=artifact
        calls=[]
        class Native:
            def run(self,argv,**kwargs):
                calls.append((argv,kwargs))
                if argv[:2]==['skopeo','login']:
                    self.assert_token=kwargs['input'];assert self.assert_token=='registry-sentinel'
                elif argv[:2]==['skopeo','copy']:
                    Path(argv[-1].removeprefix('oci-archive:')).write_bytes((Path(__file__).with_name('contracts')/'artifacts/image.oci.tar').read_bytes())
                elif argv[:2]==['trivy','image']:
                    assert '--input' in argv
                    image=Path(argv[argv.index('--input')+1]);assert image.is_file()
                    assert not image.stat().st_mode&0o077
                    assert 'GH_TOKEN' not in kwargs['env']
                    return SimpleNamespace(returncode=0,stdout='{"Results":[]}',stderr='')
                else:raise AssertionError(argv)
                return SimpleNamespace(returncode=0,stdout='',stderr='')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GH_TOKEN':'registry-sentinel','GITHUB_ACTOR':'operator'}):
            for component in data['plan']['components']:
                (Path(directory)/component['path']).mkdir(parents=True,exist_ok=True)
            results=scan(prepared,SimpleNamespace(repository='example/app'),Native(),directory,{},emit=lambda *a,**kw:None)
        self.assertTrue(any(r['scanner']=='trivy' and r['status']=='passed' for r in results))
        self.assertTrue(any(argv[:2]==['skopeo','login'] for argv,_ in calls))
        self.assertFalse(any('registry-sentinel' in str(argv) for argv,_ in calls))

    def test_workflow_has_actual_current_scan_barrier_after_stage_before_future_mutation(self):
        workflow=(ROOT/'.github/workflows/monorepo-main-build.yml').read_text()
        self.assertIn('name: monorepo-scan-barrier',workflow)
        self.assertIn('needs: [stage, scan-context, component-scan]',workflow)
        self.assertIn('uses: ./bp/ci/monorepo/scanners',workflow)
        self.assertIn('scan_entry.py run --stage-artifact-id',workflow)
        self.assertIn('scan_entry.py barrier --stage-artifact-id',workflow)
        self.assertIn('name: monorepo-component-scan-${{ matrix.component }}',workflow)
        self.assertIn('if: always()',workflow)
        self.assertNotIn('DEPLOYMENT_STATE_CONF:',workflow.split('  scan:\n',1)[1].split('\n  deployment-context:',1)[0])

if __name__=='__main__':unittest.main()
