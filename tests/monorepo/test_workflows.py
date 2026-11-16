import diagnostic_support
import argparse
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError, canonical_bytes, load_record
from executor import ExecutionError, Runner
from preview import download_bundle
from workflow import plan as workflow_plan, preview_build_baseline
from test_preview import GitHub, Kube, policy, preview_plan
from test_release import fixture


class ArchiveGitHub:
    def __init__(self, run, plan, extra=False):
        self.run=run
        self.items=[]
        self.data={}
        result=fixture('oci-image-valid')
        source=Path(__file__).with_name('contracts')/'artifacts/image.oci.tar'
        for name,files in [('monorepo-plan-12-1',{'monorepo-plan.json':canonical_bytes(plan)}),
            ('components-12-1-api',{'results/api.json':canonical_bytes(result),result['mainArtifact']['location']['path']:source.read_bytes(),**({'unexpected.txt':b'no'} if extra else {})})]:
            ident=len(self.items)+1
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as archive:
                for path,data in files.items():archive.writestr(path,data)
            self.items.append({'id':ident,'name':name,'expired':False,'workflow_run':{'id':12,'head_sha':'a'*40}})
            self.data[ident]=buffer.getvalue()
    def repo(self,method,path,data=None,**kwargs):
        if '/artifacts?' in path:return {'artifacts':self.items}
        return self.data[int(path.split('/')[3])]


class WorkflowTests(unittest.TestCase):
    def test_every_fixed_thin_caller_resolves_to_real_central_workflow(self):
        contract=json.loads((ROOT/'tests/monorepo/fixtures/revision_callers.json').read_text())
        for caller in contract['callers']:
            path=caller['reusable']
            with self.subTest(caller=caller['caller'],path=path):
                self.assertTrue(path.startswith('.github/workflows/'))
                self.assertTrue((ROOT/path).is_file(),path)
                self.assertIn('workflow_call:',(ROOT/path).read_text())
        for template in ('monorepo-app-template','monorepo-platform-template'):
            directory=ROOT.parent/template/'.github/workflows'
            if not directory.is_dir():continue
            import re
            for file in directory.glob('*'):
                if file.suffix not in ('.yml','.yaml'):continue
                for path in re.findall(r'cloudopsworks/blueprints/(\.github/workflows/[^@\s]+)@v5\.11\.0',file.read_text()):
                    self.assertTrue((ROOT/path).is_file(),str(file)+': '+path)

    def test_runner_bounds_real_process_output_and_deadline(self):
        with self.assertRaises(ExecutionError):Runner(output_limit=1024).run([sys.executable,'-c','print("x"*1000000)'])
        with self.assertRaises(ExecutionError):Runner(timeout=.05).run([sys.executable,'-c','import time;time.sleep(10)'])
        self.assertEqual(Runner().run([sys.executable,'-c','print("ok")']).stdout,'ok\n')

    def test_artifacts_exact_run_pr_bytes_and_no_extras(self):
        run=GitHub().run
        current=preview_plan()
        with tempfile.TemporaryDirectory() as directory:
            result,records=download_bundle(ArchiveGitHub(run,current),run,Path(directory),42)
            self.assertEqual(result['prNumber'],42)
            self.assertEqual(len(records),1)
        for change in ('pr','event','extra','run'):
            plan=preview_plan()
            if change=='pr':plan['prNumber']=43
            if change=='event':plan['event']='push'
            gh=ArchiveGitHub(run,plan,extra=change=='extra')
            if change=='run':gh.items[0]['workflow_run']['id']=99
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError):
                download_bundle(gh,run,Path(directory),42)

    @unittest.skipUnless(shutil.which('helm'),'Helm unavailable')
    def test_authoritative_chart_legacy_and_strict_opt_in(self):
        chart=ROOT/'kubernetes/helm/charts'
        rendered=subprocess.check_output(['helm','template','compatibility',str(chart)])
        self.assertEqual(rendered,(Path(__file__).with_name('fixtures')/'legacy-chart-default.yaml').read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            values=Path(directory)/'values.json'
            config={'monorepo':{'enabled':True,'preview':True,'image':'ghcr.io/example/api@sha256:'+'a'*64,
                'port':3000,'healthPath':'/ready','replicas':1,'host':'api.preview.example.com','ingressClass':'nginx'}}
            values.write_bytes(canonical_bytes(config))
            rendered=subprocess.check_output(['helm','template','api',str(chart),'-f',str(values)]).decode()
            self.assertIn('containerPort: 3000',rendered)
            self.assertIn('path: "/ready"',rendered)
            self.assertIn('automountServiceAccountToken: false',rendered)
            self.assertIn('kind: Ingress',rendered)
            self.assertNotIn('kind: Secret',rendered)
            self.assertFalse((ROOT/'cd/monorepo/charts').exists())
            config['monorepo']['extraObjects']=[{'kind':'Pod'}]
            values.write_bytes(canonical_bytes(config))
            rejected=subprocess.run(['helm','template','api',str(chart),'-f',str(values)],capture_output=True)
            self.assertNotEqual(rejected.returncode,0)

    def test_workflow_trusted_refs_permissions_and_arm64(self):
        for path in (ROOT/'.github/workflows').glob('monorepo-*.yml'):
            text=path.read_text()
            self.assertNotIn('github.workflow_ref',text)
            self.assertNotIn('github.workflow_sha',text)
            self.assertNotIn('ref: v5.11,',text)
            # Composite checkout refs and direct checkout.with.ref are distinct
            # supported fixed graph edges. Automerge also invokes the exact
            # trusted current-head gate before the reviewed upstream consumer.
            if path.name == 'monorepo-automerge.yml':
                self.assertIn('cloudopsworks/automerge-action@v0.17.0', text)
                self.assertIn('cloudopsworks/blueprints/cd/checkout@v5.11.0',text)
                self.assertIn('run: python3 bp/cd/monorepo/runtime/gitops.py automerge',text)
                self.assertIn("if: ${{ steps.approval.outputs.authorized == 'true' }}",text)
                self.assertIn('PULL_REQUEST: ${{ steps.approval.outputs.pull_request }}',text)
            elif path.name=='monorepo-pr-close.yml':
                self.assertIn('uses: ./.github/workflows/monorepo-preview.yml',text)
                self.assertIn('uses: ./.github/workflows/monorepo-closure.yml',text)
                self.assertNotIn('run:',text,'wrapper invokes only fixed same-revision reusable code')
            else:
                self.assertTrue('ref: v5.11.0' in text or 'cloudopsworks/blueprints/cd/checkout@v5.11.0' in text)
            import re
            for ref in re.findall(r'uses: cloudopsworks/blueprints/[^@\s]+@([^\s]+)', text):
                self.assertEqual(ref, 'v5.11.0')
            self.assertNotIn('make ',text)
        ci=(ROOT/'.github/workflows/monorepo-ci.yml').read_text()
        build=ci.split('  build:\n')[1].split('  required:\n')[0]
        self.assertNotIn('secrets:',build)
        self.assertNotIn('id-token:',ci)
        self.assertIn('docker/setup-qemu-action@v3',build)
        self.assertIn('docker/setup-buildx-action@v3',build)
        preview=(ROOT/'.github/workflows/monorepo-preview.yml').read_text()
        self.assertIn("checkout_source: 'false'",preview)
        self.assertIn('blueprint_ref: v5.11.0',preview)
        self.assertIn('runtime/preview_entry.py discover',preview)
        self.assertNotIn('actions/checkout@',preview,'source policy is API-fetched data, never a mutable default-branch checkout')
        self.assertNotIn('pull_request.head',preview)
        self.assertIn('cancel-in-progress: false',preview)
        self.assertIn('monorepo-preview-${{ github.repository_id }}-${{ matrix.pr }}-${{ matrix.id }}',preview)

    def test_only_reviewed_privileged_graph_is_exposed(self):
        fixture=json.loads((ROOT/'tests/monorepo/fixtures/revision_callers.json').read_text())
        retired={'monorepo-release.yml','monorepo-deploy.yml'}
        self.assertFalse(any(Path(row['reusable']).name in retired for row in fixture['callers']))
        for name in retired:self.assertFalse((ROOT/'.github/workflows'/name).exists())
        with tempfile.TemporaryDirectory() as directory:
            for command in ('baseline','publish','deploy','targets','resolve','preflight','apply'):
                result=subprocess.run([sys.executable,str(ROOT/'cd/monorepo/runtime/workflow.py'),command,'--help'],
                    cwd=directory,env={'PATH':'','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2,(command,result.stdout,result.stderr))
                self.assertIn('invalid choice',result.stderr)
                self.assertNotIn('Traceback',result.stderr)

    def test_deploy_tools_are_explicit_and_resolve_has_bootstrap(self):
        tools=(ROOT/'cd/monorepo/tools/action.yml').read_text()
        auth=(ROOT/'cd/monorepo/auth/action.yml').read_text()
        for pin in ('v4.3.1','v1.37.2','2.40.1','2.90.0','skopeo=1.13.3+ds1-2ubuntu0.24.04.3'):
            self.assertIn(pin,tools)
        self.assertIn("'553.0.0'",auth)
        self.assertIn('Google Cloud SDK',auth)
        deploy=(ROOT/'.github/workflows/monorepo-main-build.yml').read_text()
        resolve=deploy.split('  preflight:')[1].split('  preflight-barrier:')[0]
        self.assertIn('/cd/monorepo/tools',resolve)
        self.assertIn('CLOUDOPSWORKS_KUBECTL_VERSION',resolve)
        self.assertIn('normal_entry.py preflight',resolve)

    def test_unknown_preview_baseline_materializes_all_read_only(self):
        record=preview_plan()
        self.assertEqual(preview_build_baseline(record,Path('.'),Kube(),lambda _:None),(None,True))

    @unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'set TRONADOR_TEST_BINARY to source-built CLI')
    def test_source_cli_first_partial_materialization_then_incremental(self):
        binary=Path(os.environ['TRONADOR_TEST_BINARY']).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            dot=root/'.cloudopsworks';(dot/'vars').mkdir(parents=True)
            config={'schemaVersion':2,'config':{'gitFlow':{'enabled':False}},'ci':{'sharedPaths':['.github/**'],'maxParallel':1},'components':{},
                'cd':{'preview':{'config':'preview.yaml'},'deployments':{'release':{'env':'prod'}}}}
            for ident in ('api','web'):
                config['components'][ident]={'path':'components/'+ident,'language':'go','framework':'plain','runtime':'1.26.7',
                    'build':{'profile':'go'},'package':{'kind':'container','dockerfile':'Dockerfile','context':'.','platform':'linux/amd64'},
                    'workload':{'kind':'http','port':3000,'healthPath':'/ready'},'preview':{'mode':'container','source':'main','port':3000,'healthPath':'/ready'},'dependsOn':[],'watch':[],'targets':['prod-run']}
                path=root/'components'/ident;path.mkdir(parents=True);(path/'main.go').write_text('package main\nfunc main(){}\n');(path/'Dockerfile').write_text('FROM scratch\n')
            (dot/'cloudopsworks-ci.yaml').write_bytes(canonical_bytes(config));(dot/'.monorepo').touch()
            target=preview_plan()['targets'][0]
            for generated in ('configDigest','id','environment'): target.pop(generated)
            (dot/'vars/inputs-prod.yaml').write_bytes(canonical_bytes({'monorepo':{'targets':{'prod-run':target}}}));(dot/'preview.yaml').write_bytes(canonical_bytes({'enabled':True,'targets':[policy()]}))
            def git(*args):return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()
            git('init','-b','main');git('config','user.email','test@example.com');git('config','user.name','Test');git('add','.');git('commit','-m','base');base=git('rev-parse','HEAD')
            (root/'components/api/main.go').write_text('package main\nfunc main(){println(1)}\n');git('add','.');git('commit','-m','api');first=git('rev-parse','HEAD')
            bin_dir=root/'bin';bin_dir.mkdir();(bin_dir/'tronador').symlink_to(binary)
            event=root/'event.json';event.write_text('{"number":42,"pull_request":{"number":42}}')
            output=root/'outputs';output.touch()
            env={'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],'GITHUB_EVENT_PATH':str(event),'GITHUB_OUTPUT':str(output),
                'GITHUB_REPOSITORY_ID':'12345','GITHUB_REPOSITORY':'example/mixed-app','GH_TOKEN':'read-only-test','CLOUDOPSWORKS_AUTOMATION_ID':'99'}
            class DiagnosticRunner(Runner):
                def run(self, argv, **kwargs):
                    result=super().run(argv,**kwargs)
                    if result.returncode and argv[0]=='tronador':
                        raise AssertionError(result.stderr)
                    return result
            args=argparse.Namespace(root=root,base=base,head=first,event='pull-request',version='0.0.0-pr.42',out=root/'plan.json',all=False)
            class Store:
                value=None
                def __init__(self,*args):pass
                def load(self):return self.value
            with patch.dict(os.environ,env),patch('workflow.GitHub'),patch('preview.PreviewStore',Store):
                workflow_plan(args,DiagnosticRunner())
                initial=load_record(args.out)
                self.assertEqual(initial['prNumber'],42)
                self.assertIn('max-parallel=1',output.read_text())
                self.assertEqual({s['componentId'] for s in initial['buildSelection']},{'api','web'})
                state=fixture('preview-state');state.update(headSha=first,targetId='prod-run')
                Store.value={'state':state,'artifacts':{'api':{},'web':{}}}
                (root/'components/web/main.go').write_text('package main\nfunc main(){println(2)}\n');git('add','.');git('commit','-m','web');second=git('rev-parse','HEAD')
                args.head=second
                workflow_plan(args,DiagnosticRunner())
                incremental=load_record(args.out)
                self.assertEqual(incremental['baseSha'],first)
                self.assertEqual([s['componentId'] for s in incremental['buildSelection']],['web'])


if __name__=='__main__':unittest.main()
