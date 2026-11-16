import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,digest
from iac_values import ValuesError,render_values,recovery_values

FIXTURES=Path(__file__).with_name('contracts')


class ValuesTests(unittest.TestCase):
    def setUp(self):
        self.plan=json.loads((Path(__file__).with_name('fixtures')/'operations/destroy-plan.json').read_text())
        self.plan['operation']='apply';h=self.plan['stateHandle']
        self.plan['inputs']={'resource':copy.deepcopy(h['resourceIdentity']),'configuration':{'kind':'aws.eks'},'workload':{'kind':'http','port':8080,'healthPath':'/health'}}
        self.metadata={'moduleId':'aws-eks','variables':{'resource':['kind','cluster','missing.optional'],'configuration':['kind'],'workload':['kind','port'],'artifact':['digest','format','path','imageReference','files'],'owner_digest':[]}}
        self.artifact=json.loads((FIXTURES/'valid/zip-valid.json').read_text())['mainArtifact']
        self.payload=FIXTURES/'artifacts/app.zip'
    def work(self,directory):
        p=Path(directory)/'private';p.mkdir(mode=0o700);return p

    def test_verified_zip_snapshot_and_exact_projection_no_extra_fields(self):
        with tempfile.TemporaryDirectory() as d:
            result=render_values(self.plan,self.metadata,self.artifact,work=self.work(d),artifact_path=self.payload)
            self.assertEqual(result['resource'],{'kind':'aws.eks','cluster':'example'})
            self.assertEqual(result['owner_digest'],digest(self.plan['stateHandle']))
            copied=Path(result['artifact']['path'])
            self.assertEqual(copied.read_bytes(),self.payload.read_bytes())
            self.assertEqual(copied.stat().st_mode&0o777,0o600)
            self.assertNotIn('authRef',json.dumps(result))

    def test_static_zip_files_and_reserved_marker_from_verified_data(self):
        artifact={**self.artifact,'kind':'static'}
        marker={'artifactDigest':artifact['digest'],'releaseVersion':'1.2.3','idempotencyKey':'sha256:'+'f'*64}
        with tempfile.TemporaryDirectory() as d:
            result=render_values(self.plan,self.metadata,artifact,work=self.work(d),artifact_path=self.payload,static_marker=marker)
            files=result['artifact']['files'];self.assertTrue(files)
            self.assertIn('.cloudopsworks-release.json',[p['key'] for p in files])
            actual=next(p for p in files if p['key']=='.cloudopsworks-release.json')
            self.assertEqual(json.loads(Path(actual['path']).read_bytes()),marker)
            self.assertTrue(all(Path(p['path']).is_file() for p in files))

    def test_wrong_bytes_bad_descriptor_and_untrusted_image_rejected(self):
        for artifact,payload in (({**self.artifact,'digest':'sha256:'+'0'*64},self.payload),({**self.artifact,'digest':'sha256:../../escape'},self.payload)):
            with tempfile.TemporaryDirectory() as d,self.assertRaises((ContractError,ValuesError)):
                render_values(self.plan,self.metadata,artifact,work=self.work(d),artifact_path=payload)
        image={**self.artifact,'kind':'container','format':'oci','location':{'kind':'oci','reference':'ghcr.io/example/api@'+self.artifact['digest']}}
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValuesError):
            render_values(self.plan,self.metadata,image,work=self.work(d),image_reference='https://evil/?token=sentinel')

    def test_existing_rest_uses_only_verified_native_configuration_projection(self):
        plan=copy.deepcopy(self.plan);h=plan['stateHandle']
        resource={'provider':'aws','kind':'aws.apigateway-rest','region':'us-east-1','restApiId':'abc123','stage':'prod','ownership':'managed'}
        h['resourceIdentity']=resource;h['moduleId']='aws-apigateway-rest'
        plan['inputs']={'resource':copy.deepcopy(resource),'configuration':{'kind':'aws.apigateway-rest'},'workload':{'kind':'api'}}
        plan['stateHandleDigest']=digest(h)
        metadata={'moduleId':'aws-apigateway-rest','variables':{'resolved_api':['name','description']}}
        native={'name':'original-api','description':'original description'}
        with tempfile.TemporaryDirectory() as d:
            result=render_values(plan,metadata,self.artifact,work=self.work(d),artifact_path=self.payload,resolved_api=native)
            self.assertEqual(result,{'resolved_api':native})
        for candidate in ({**native,'token':'sentinel'},{**native,'description':'bad\nheader'}, {'name':'','description':''}):
            with tempfile.TemporaryDirectory() as d,self.assertRaises(ValuesError):
                render_values(plan,metadata,self.artifact,work=self.work(d),artifact_path=self.payload,resolved_api=candidate)

    def test_beanstalk_dockerrun_requires_exact_immutable_data_only_zip(self):
        plan=copy.deepcopy(self.plan);h=plan['stateHandle']
        resource={'provider':'aws','kind':'aws.beanstalk','region':'us-east-1','application':'app',
            'environmentName':'api','bucket':'packages','prefix':'api','ownership':'managed'}
        h.update(resourceIdentity=resource,moduleId='aws-beanstalk')
        plan['inputs']={'resource':resource,'configuration':{'kind':'aws.beanstalk','iac':{'solutionStackName':'64bit Amazon Linux Docker'}},'workload':{'kind':'http','port':8080,'healthPath':'/health'}}
        plan['stateHandleDigest']=digest(h)
        metadata={'moduleId':'aws-beanstalk','variables':{'artifact':['digest','imageReference']}}
        reference='registry.example/api@sha256:'+'a'*64
        document={'AWSEBDockerrunVersion':'1','Image':{'Name':reference,'Update':'true'},'Ports':[{'ContainerPort':'8080'}]}
        for bad in (None,'mutable','dockerfile','duplicate','other-port'):
            with self.subTest(case=bad),tempfile.TemporaryDirectory() as d:
                payload=Path(d)/'package.zip';value=copy.deepcopy(document)
                if bad=='mutable':value['Image']['Name']='registry.example/api:latest'
                if bad=='other-port':value['Ports'][0]['ContainerPort']='65536'
                with zipfile.ZipFile(payload,'w') as archive:
                    raw=json.dumps(value)
                    if bad=='duplicate':raw=raw[:-1]+',"Image":{"Name":"registry.example/evil:latest"}}'
                    archive.writestr('Dockerrun.aws.json',raw)
                    if bad=='dockerfile':archive.writestr('Dockerfile','FROM mutable:latest')
                artifact={**self.artifact,'digest':'sha256:'+hashlib.sha256(payload.read_bytes()).hexdigest(),'sizeBytes':payload.stat().st_size}
                if bad:
                    with self.assertRaises((ContractError,ValuesError)):
                        render_values(plan,metadata,artifact,work=self.work(d),artifact_path=payload)
                else:
                    result=render_values(plan,metadata,artifact,work=self.work(d),artifact_path=payload)
                    self.assertEqual(result['artifact']['imageReference'],reference)

    def test_artifact_only_preview_environment_consumes_no_application_payload(self):
        handle=json.loads((Path(__file__).with_name('fixtures')/'operations/state-preview.json').read_text())
        plan=copy.deepcopy(self.plan);plan.update(operation='preview',stateHandle=handle,stateHandleDigest=digest(handle))
        plan['inputs']={'resource':copy.deepcopy(handle['resourceIdentity']),
            'configuration':{'kind':'aws.eks'},'workload':{'kind':'artifact'}}
        metadata=json.loads((ROOT/'terraform/monorepo/modules/kubernetes-preview-environment/inputs.json').read_text())
        self.assertNotIn('artifact',metadata['variables'])
        artifact=json.loads((FIXTURES/'valid/openapi-yaml-valid.json').read_text())['mainArtifact']
        with tempfile.TemporaryDirectory() as d:
            work=self.work(d)
            result=render_values(plan,metadata,artifact,work=work,kubeconfig_path='/private/config')
            self.assertEqual(result['workload'],{'kind':'artifact'})
            self.assertEqual(result['namespace'],handle['resourceIdentity']['namespace'])
            self.assertEqual(list(work.iterdir()),[])
            self.assertNotIn('artifact',result)

    def test_preview_root_recovery_has_no_artifact_or_scaffold(self):
        handle=json.loads((Path(__file__).with_name('fixtures')/'operations/state-preview.json').read_text())
        inputs={'resource':copy.deepcopy(handle['resourceIdentity']),
            'configuration':{'kind':'aws.eks'},'workload':{'kind':'artifact'}}
        metadata=json.loads((ROOT/'terraform/monorepo/modules/kubernetes-preview-environment/inputs.json').read_text())
        isolation={'probeImage':'registry.example/probe@sha256:'+'a'*64,
            'controlNamespace':'control','ingressNamespace':'ingress',
            'ingressNamespaceSelector':{'name':'ingress'},'ingressPodSelector':{'app':'ingress'},
            'dnsNamespaceSelector':{'name':'system'},'dnsPodSelector':{'app':'dns'}}
        state={'version':4,'resources':[]}
        with tempfile.TemporaryDirectory() as directory:
            work=self.work(directory)
            values=recovery_values(inputs,metadata,handle,state,work=work,
                kubeconfig_path='/private/config',preview_isolation=isolation)
            self.assertEqual(values['namespace'],handle['resourceIdentity']['namespace'])
            self.assertEqual(values['isolation'],isolation)
            self.assertEqual(values['owner_digest'],digest(handle))
            self.assertNotIn('artifact',values);self.assertEqual(list(work.iterdir()),[])
        for invalid in (None,{**isolation,'probeImage':'mutable:latest'},{**isolation,'arbitrary':'sentinel'}):
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(ValuesError):
                recovery_values(inputs,metadata,handle,state,work=self.work(directory),preview_isolation=invalid)

    def test_public_workspace_and_unknown_projection_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            work=self.work(d);work.chmod(0o755)
            with self.assertRaises(ValuesError):render_values(self.plan,self.metadata,self.artifact,work=work,artifact_path=self.payload)
        with tempfile.TemporaryDirectory() as d:
            metadata=copy.deepcopy(self.metadata);metadata['variables']['arbitrary_env']=[]
            with self.assertRaises(ValuesError):render_values(self.plan,metadata,self.artifact,work=self.work(d),artifact_path=self.payload)


if __name__=='__main__':unittest.main()
