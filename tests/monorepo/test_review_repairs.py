import diagnostic_support
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json
import os
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from test_preview import preview_plan
from workflow import preview_build_baseline, plan
from test_release import fixture

class ReviewRepairs(unittest.TestCase):
    def test_preview_baseline_requires_independent_members(self):
        record=preview_plan()
        record['components'][0]['targetIds']=[]
        state=fixture('preview-state');state.update(repository=record['repository'],prNumber=record['prNumber'],targetId='prod-run')
        payload={'state':state,'artifacts':{}}
        runner=SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(returncode=0))
        self.assertEqual(preview_build_baseline(record,Path('.'),runner,lambda _:payload),(None,True))

    def test_validated_config_concurrency_is_capped(self):
        record=preview_plan();record['previewPolicy']['enabled']=False;record['previewPolicy']['targets']=[]
        class Runner:
            def run(self,argv,**kw):
                return SimpleNamespace(returncode=0,stdout=json.dumps({'maxParallel':1} if 'validate' in argv else record),stderr='')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'outputs';out.touch()
            args=SimpleNamespace(root=root,base=record['baseSha'],head=record['headSha'],event='manual',version=record['version'],all=False,out=root/'plan.json',max_parallel=4)
            with patch.dict(os.environ,{'GITHUB_OUTPUT':str(out),'GITHUB_REPOSITORY_ID':record['repository']['id'],'GITHUB_REPOSITORY':record['repository']['fullName']}):plan(args,Runner())
            self.assertIn('max-parallel=1',out.read_text())

    def test_mixed_native_preview_and_durable_spec_carry(self):
        import hashlib,io,zipfile
        from preview import reconcile_preview,IaCPreview,namespace
        from test_preview import GitHub,Kube,StateStore
        from test_release import Publisher
        from contracts import validate_record,ContractError
        record=preview_plan();template=record['components'][0];record['components']=[];record['buildSelection']=[];record['matrix']['include']=[]
        packages={
            'function':{'kind':'function','provider':'aws','mode':'aws-zip','runtime':'provided.al2023','entryPoint':'handler','architecture':'amd64','source':'.'},
            'static':{'kind':'static','directory':'public','index':'index.html'},
            'archive':{'kind':'archive','format':'zip','include':['.']},
            'spec':{'kind':'openapi','file':'openapi.json','version':'3.0'}}
        spec=b'{"openapi":"3.0.3","info":{"title":"API","version":"1"},"paths":{}}'
        results=[]
        for ident,package in packages.items():
            component=copy.deepcopy(template);component.update(id=ident,path='components/'+ident,package=package,targetIds=[])
            component['toolchains'][0]['components']=[ident]
            if ident=='function':component['preview']={'mode':'container','source':'function','dockerfile':'Dockerfile.preview','context':'.','adapter':'handler-http','entryPoint':'handler','port':8080,'healthPath':'/health','invokePath':'/invoke','invokeTest':{'requestBody':'{}','expectedStatus':200,'responseContains':'ok'}}
            elif ident=='static':component['preview']['source']='static'
            elif ident=='archive':component['preview'].update(source='dockerfile',dockerfile='Dockerfile.preview',context='.')
            else:component['preview']={'mode':'artifact-only','reason':'openapi'}
            record['components'].append(component);record['buildSelection'].append({'componentId':ident,'reasons':['explicit-all']})
            row=copy.deepcopy(preview_plan()['matrix']['include'][0]);row.update(componentId=ident,closure=[ident]);row['toolchains'][0]['components']=[ident];record['matrix']['include'].append(row)
            result=fixture('component-result');result['componentId']=ident;result['mainArtifact'].update(kind=package['kind'],format='openapi-json' if ident=='spec' else 'zip')
            if ident=='spec':
                result['mainArtifact'].update(digest='sha256:'+hashlib.sha256(spec).hexdigest(),sizeBytes=len(spec),location={'kind':'local','path':'.cloudopsworks/out/spec/1.2.3/main.json'})
                result['previewArtifact']=None
            results.append(result)
        validate_record(record)
        source={'artifactId':'99','runId':'12','runAttempt':'1','headSha':record['headSha'],'componentId':'spec','path':results[-1]['mainArtifact']['location']['path'],'name':'components-12-1-spec','url':'https://github.com/example/mixed-app/actions/runs/12/artifacts/99'}
        class Github(GitHub):
            def __init__(self):super().__init__();self.expired=False;self.corrupt=False;self.downloads=0
            def repo(self,method,path,data=None,**kwargs):
                if path=='/actions/artifacts/99':return {'name':source['name'],'expired':self.expired,'workflow_run':{'id':12,'head_sha':record['headSha']}}
                if path.endswith('/99/zip'):
                    self.downloads+=1;buffer=io.BytesIO()
                    with zipfile.ZipFile(buffer,'w') as archive:archive.writestr(source['path'],b'corrupt' if self.corrupt else spec)
                    return buffer.getvalue()
                return super().repo(method,path,data)
        gh=Github();ex=Kube();store=StateStore();deployed=[];verified=[]
        from test_preview_workflow import runtime
        _,_,_,engine,runtime_context,handles,_=runtime(gh)
        child=copy.deepcopy(handles[0]);child.update(scope='preview-component',componentId='static');handles.append(child)
        runtime_context['cloud']=ex
        controller=IaCPreview(gh,record['repository'],42,'prod-run',record['headSha'],runtime_context)
        context={'controller':controller,'artifact_sources':{'spec':source},'isolation':lambda *a:fixture('preview-state')['isolation'],
            'deploy_component':lambda *a,**kw:deployed.append(a[2]['id']),'verify_component':lambda *a,**kw:verified.append(a[2]['id'])}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':str(Path(directory)/'diagnostics')}),patch.object(controller,'environment',return_value={'namespace':namespace(record['repository']['id'],42,'prod-run')}),patch('preview.isolation_preflight',return_value=fixture('preview-state')['isolation']):
            root=Path(directory);file=root/source['path'];file.parent.mkdir(parents=True);file.write_bytes(spec)
            def run(current_results):return reconcile_preview(ex,gh,record['repository'],42,gh.run,record,record,current_results,'prod-run',Publisher(),root,store,context=context)
            state=run(results)
            self.assertEqual(deployed,['function','static','archive']);self.assertEqual(len(state['components']),4)
            self.assertEqual(state['components'][-1]['status'],'artifact-only');self.assertIsNone(state['components'][-1]['releaseName'])
            self.assertEqual(store.value['artifactSources']['spec']['url'],source['url'])
            events=[json.loads(line) for line in (root/'diagnostics/events.jsonl').read_text().splitlines()]
            spec_event=next(row for row in events if row['phase']=='preview-spec')
            self.assertEqual(spec_event['artifactUrl'],source['url']);self.assertEqual(spec_event['namespace'],state['namespace']);self.assertEqual(spec_event['provider'],'gcp')
            readiness=[row for row in events if row['phase']=='preview-readiness']
            self.assertEqual(len(readiness),4);self.assertEqual(readiness[-1]['status'],'artifact-only')
            record.update(baseSha=record['headSha'],buildNoop=True,buildSelection=[],matrix={'include':[]})
            deployed.clear();run([]);self.assertEqual(deployed,[]);self.assertEqual(verified,['function','static','archive']);self.assertEqual(gh.downloads,2)
            record['components']=[c for c in record['components'] if c['id']!='static'];record['removedComponents']=['static']
            run([]);self.assertTrue(any(p['operation']=='destroy' and p['stateHandle']['componentId']=='static' for p in engine.calls))
            self.assertFalse(any(argv[0]=='helm' for argv,_ in ex.calls))
            gh.expired=True
            with self.assertRaises(ContractError):run([])
            gh.expired=False;gh.corrupt=True
            with self.assertRaises(ContractError):run([])

    def test_diagnostics_redact_exception_messages_and_invalid_context(self):
        import io
        from contextlib import redirect_stdout
        from diagnostics import event,error_category
        from contracts import ContractError
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':directory}):
            stream=io.StringIO()
            with redirect_stdout(stream):
                event('apply','failed',component='api',errorCategory=error_category(ContractError('readiness-timeout','SENTINEL_SECRET')),message='SENTINEL_SECRET',target='bad\nSENTINEL_SECRET')
                event('apply','failed',errorCategory=error_category(RuntimeError('SENTINEL_SECRET')))
            stored=(Path(directory)/'events.jsonl').read_text()
            self.assertNotIn('SENTINEL_SECRET',stored+stream.getvalue())
            self.assertIn('readiness-timeout',stored);self.assertIn('internal-error',stored)

    def test_failed_deployment_result_is_persisted_before_failure_exit(self):
        from workflow import apply_row
        from contracts import ContractError,canonical_bytes
        request=fixture('deployment-request');manifest=fixture('release-manifest')
        result=fixture('deployment-result');result.update(status='failed',ready=False,resourceUrl=None,error={'code':'serving-timeout','message':'Native deployment or serving verification failed','retryable':False})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'manifest.json').write_bytes(canonical_bytes(manifest));(root/'rows.json').write_bytes(canonical_bytes([{'request':request,'resolved':{}}]))
            args=SimpleNamespace(manifest=root/'manifest.json',rows=root/'rows.json',component=request['componentId'],target=request['target']['id'],force=False)
            def run(*args,**kwargs):kwargs['context']['result_sink'](result);return [result]
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ,{'CLOUDOPSWORKS_AUTOMATION_ID':'99','CLOUDOPSWORKS_DIAGNOSTICS':str(root/'events')}),patch('workflow.verify_manifest'),patch('workflow.assert_mapping'),patch('workflow.reconcile',side_effect=run):
                    with self.assertRaises(ContractError):apply_row(args,None,None,None)
                stored=json.loads(next((root/'.lifecycle-diagnostics').glob('deployment-*.json')).read_bytes())
                self.assertEqual(stored['error']['code'],'serving-timeout')
                self.assertEqual(stored['status'],'failed')
            finally:os.chdir(previous)

    def test_concurrency_bounds_and_caller_cap(self):
        from contracts import ContractError
        record=preview_plan();record['previewPolicy']={'enabled':False,'targets':[]}
        for configured,cap,expected in [(8,2,2),(1,32,1),(32,32,32),(0,4,None),(33,4,None),(4,0,None),(4,33,None),(1.5,4,None)]:
            with self.subTest(configured=configured,cap=cap),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);outputs=root/'outputs';outputs.touch()
                args=SimpleNamespace(root=root,base=record['baseSha'],head=record['headSha'],event='manual',version=record['version'],all=False,out=root/'plan.json',max_parallel=cap)
                runner=SimpleNamespace(run=lambda argv,**kw:SimpleNamespace(returncode=0,stdout=json.dumps({'maxParallel':configured} if 'validate' in argv else record),stderr=''))
                with patch.dict(os.environ,{'GITHUB_OUTPUT':str(outputs),'GITHUB_REPOSITORY_ID':record['repository']['id'],'GITHUB_REPOSITORY':record['repository']['fullName']}):
                    if expected is None:
                        with self.assertRaises(ContractError):plan(args,runner)
                    else:
                        plan(args,runner);self.assertIn('max-parallel='+str(expected),outputs.read_text())

    def test_failed_source_phase_keeps_safe_context_not_process_output(self):
        import io
        from contextlib import redirect_stdout
        from workflow import build
        from executor import ExecutionError
        from contracts import canonical_bytes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'plan.json').write_bytes(canonical_bytes(preview_plan()))
            args=SimpleNamespace(plan=root/'plan.json',component='api',root=root,bundle=root/'bundle')
            runner=SimpleNamespace(run=lambda *args,**kw:SimpleNamespace(returncode=1,stdout='SENTINEL_SECRET',stderr='SENTINEL_SECRET'))
            stream=io.StringIO()
            with patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':str(root/'diagnostics')}),redirect_stdout(stream),self.assertRaises(ExecutionError):build(args,runner)
            rows=[json.loads(line) for line in (root/'diagnostics/events.jsonl').read_text().splitlines()]
            self.assertTrue(any(row.get('component')=='api' and row['phase']=='build' and row.get('errorCategory')=='process-failed' for row in rows))
            self.assertNotIn('SENTINEL_SECRET',stream.getvalue())
            failed=json.loads((root/'diagnostics/component-api.json').read_bytes())
            self.assertEqual(failed['status'],'failed');self.assertEqual(failed['error']['code'],'process-failed')

    def test_preview_observability_safe_links_namespace_and_cleanup_outcomes(self):
        from diagnostics import event
        from preview import cleanup,namespace,owner
        from test_preview import GitHub,Kube
        repo=fixture('build-plan')['repository'];name=namespace(repo['id'],42,'prod-run')
        link={'repository':repo['fullName'],'runId':'12','artifactId':'99','url':'https://github.com/'+repo['fullName']+'/actions/runs/12/artifacts/99'}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':directory}):
            result=event('preview-spec','published',namespace=name,provider='gcp',artifactLink=link)
            self.assertEqual(result.get('artifactUrl'),link['url'])
            self.assertEqual(result.get('namespace'),name);self.assertEqual(result.get('provider'),'gcp')
            for bad in ('https://evil.test/SENTINEL_SECRET','https://github.com/'+repo['fullName']+'/actions/runs/12/artifacts/99?token=SENTINEL_SECRET','https://user:SENTINEL_SECRET@github.com/'+repo['fullName']+'/actions/runs/12/artifacts/99'):
                bad_link=dict(link,url=bad)
                record=event('preview-spec','failed',artifactLink=bad_link,artifactUrl=bad,namespace='bad\nSENTINEL_SECRET',provider='SENTINEL_SECRET')
                self.assertNotIn('SENTINEL_SECRET',json.dumps(record));self.assertNotIn('artifactUrl',record)
            from preview import IaCPreview
            from test_preview_workflow import runtime
            gh,repo,ex,engine,runtime_context,handles,native=runtime()
            gh.pr['state']='closed'
            controller=IaCPreview(gh,repo,42,'prod-run','a'*40,runtime_context)
            saved=copy.deepcopy(handles);handles.clear();ex.ns=None
            cleanup(ex,gh,repo,42,'prod-run',lambda _:None,provider='gcp',context={'controller':controller})
            handles.extend(saved)
            ex.ns={'metadata':{'labels':owner(repo,42,'prod-run'),'uid':'uid-1',
                'annotations':{'cloudopsworks.io/owner-digest':__import__('contracts').digest(handles[0])}}}
            engine.after=lambda plan:(setattr(ex,'ns',None),native.clear())
            cleanup(ex,gh,repo,42,'prod-run',lambda _:None,provider='gcp',context={'controller':controller})
            self.assertEqual(len(engine.calls),1)
            self.assertEqual(engine.calls[0]['operation'],'destroy')
            self.assertFalse(any(argv[1] in ('delete','apply','create') for argv,_ in ex.calls))
            rows=[json.loads(line) for line in (Path(directory)/'events.jsonl').read_text().splitlines()]
            cleanup_rows=[row for row in rows if row['phase']=='preview-cleanup']
            self.assertEqual([row['status'] for row in cleanup_rows],['noop','deleted'])
            self.assertTrue(all(row['namespace']==name and row['provider']=='gcp' for row in cleanup_rows))
