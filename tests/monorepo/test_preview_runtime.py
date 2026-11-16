"""Read-only private native-state binding, no hosted or credentialed proof."""
import copy
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,digest
from preview_runtime import owned_environment,context,_cluster
from test_preview_workflow import fixture_handle
from test_preview import preview_plan


def native_state(handle):
    name=handle['resourceIdentity']['namespace'];hd=digest(handle);uid='namespace-uid'
    identity=handle['origin']['repository']['id']+':'+str(handle['prNumber'])+':'+handle['targetId']
    suffix=hashlib.sha256(identity.encode()).hexdigest()[:20]
    probes={}
    for key,parent in [('canary',name),('control','control'),('ingress','ingress')]:
        pod='cloudopsworks-canary' if key=='canary' else 'cw-'+key+'-'+suffix
        probes[key]={'id':parent+'/'+pod,'name':pod,'namespace':parent,'uid':key+'-uid'}
    policies={'default_deny':'cloudopsworks-default-deny','same_namespace':'cloudopsworks-same-namespace',
        'dns':'cloudopsworks-dns','ingress':'cloudopsworks-ingress'}
    owned={'namespace':name,'uid':uid,'owner_digest':hd,
        'ownedIds':{'namespace':name,'policies':[name+'/'+p for p in policies.values()],'probes':probes}}
    def resource(kind,rname,attrs,index=None):
        instance={'attributes':attrs}
        if index is not None:instance['index_key']=index
        return {'mode':'managed','type':kind,'name':rname,'instances':[instance]}
    metadata={'name':name,'uid':uid,'annotations':{'cloudopsworks.io/owner-digest':hd}}
    resources=[resource('kubernetes_namespace_v1','environment',{'id':name,'metadata':[metadata]})]
    for key,value in policies.items():
        resources.append(resource('kubernetes_network_policy_v1',key,{'id':name+'/'+value,
            'metadata':[dict(metadata,name=value,namespace=name)]}))
    for key,probe in probes.items():
        meta={'name':probe['name'],'namespace':probe['namespace'],'uid':probe['uid'],
            'annotations':{'cloudopsworks.io/owner-digest':hd,'cloudopsworks.io/environment-uid':uid}}
        resources.append(resource('kubernetes_pod_v1','probe',{'id':probe['id'],'metadata':[meta]},key))
    # Native provider groups all indexed probe instances in one resource.
    members=[r for r in resources if r['type']=='kubernetes_pod_v1']
    resources=[r for r in resources if r['type']!='kubernetes_pod_v1']+[dict(members[0],instances=[r['instances'][0] for r in members])]
    return {'version':4,'outputs':{'owned':{'sensitive':False,'value':owned}},'resources':resources}


class PreviewNativeStateTests(unittest.TestCase):
    def test_complete_namespace_policy_and_external_probe_uid_native_binding(self):
        handle=fixture_handle(preview_plan()['repository']);state=native_state(handle)
        expected=copy.deepcopy(state['outputs']['owned']['value']);expected['ownedIds']['policies'].sort()
        self.assertEqual(owned_environment(handle,state),expected)
        for mutation in ('uid','owner','probe','address','sensitive','extra','duplicate'):
            changed=copy.deepcopy(state)
            if mutation=='uid':changed['resources'][0]['instances'][0]['attributes']['metadata'][0]['uid']='foreign'
            elif mutation=='owner':changed['outputs']['owned']['value']['owner_digest']='sha256:'+'0'*64
            elif mutation=='probe':changed['resources'][-1]['instances'][0]['attributes']['metadata'][0]['annotations']['cloudopsworks.io/environment-uid']='foreign'
            elif mutation=='address':changed['resources'][1]['name']='foreign'
            elif mutation=='sensitive':changed['outputs']['owned']['sensitive']=True
            elif mutation=='extra':changed['resources'].append(dict(changed['resources'][0],name='foreign'))
            else:changed['resources'].append(copy.deepcopy(changed['resources'][0]))
            with self.subTest(mutation=mutation),self.assertRaises(ContractError):owned_environment(handle,changed)
        self.assertIsNone(owned_environment(handle,{'version':4,'resources':[],'outputs':{}}))

    def test_partial_native_apply_or_destroy_recovers_without_success_outputs(self):
        handle=fixture_handle(preview_plan()['repository']);state=native_state(handle)
        state['resources']=state['resources'][:2]
        state['outputs']={}
        actual=owned_environment(handle,state)
        self.assertEqual(actual['uid'],'namespace-uid')
        self.assertEqual(len(actual['ownedIds']['policies']),1)
        self.assertEqual(actual['ownedIds']['probes'],{})
        # Stale successful outputs must not override newer actual checkpoints.
        state=native_state(handle)
        state['resources'][-1]['instances'][0]['attributes']['metadata'][0]['uid']='new-native-probe-uid'
        actual=owned_environment(handle,state)
        self.assertEqual(actual['ownedIds']['probes']['canary']['uid'],'new-native-probe-uid')
        state['resources'].reverse()
        self.assertEqual(owned_environment(handle,state),actual)

    def test_namespace_resource_and_outputs_must_agree_not_just_owner_labels(self):
        handle=fixture_handle(preview_plan()['repository']);state=native_state(handle)
        state['outputs']['owned']['value']['namespace']='another'
        with self.assertRaises(ContractError):owned_environment(handle,state)

    def test_aws_cluster_account_endpoint_and_ca_match_private_kubeconfig(self):
        target={'provider':'aws','kind':'aws.eks','region':'us-east-1','cluster':'cluster'}
        class Native:
            def __init__(self):self.calls=[];self.ca='trusted-ca';self.account='123456789012'
            def run(self,argv,**kwargs):
                self.calls.append(argv)
                if 'get-caller-identity' in argv:value={'Account':self.account}
                elif 'describe-cluster' in argv:value={'cluster':{'arn':'arn:aws:eks:us-east-1:123456789012:cluster/cluster',
                    'endpoint':'https://cluster.example','certificateAuthority':{'data':'trusted-ca'}}}
                else:value={'current-context':'trusted','contexts':[{'name':'trusted','context':{'cluster':'cluster'}}],
                    'clusters':[{'name':'cluster','cluster':{'server':'https://cluster.example','certificate-authority-data':self.ca}}]}
                return subprocess.CompletedProcess(argv,0,json.dumps(value),'')
        native=Native();account,claim=_cluster(target,native,'/private/kubeconfig','123456789012')
        self.assertEqual(account,'123456789012');self.assertTrue(claim.endswith(':cluster/cluster'))
        self.assertFalse(any(a[0] in ('terraform','tofu','terragrunt') or any(v in a for v in ('apply','delete','create','upgrade')) for a in native.calls))
        native.ca='different-ca'
        with self.assertRaises(ContractError):_cluster(target,native,'/private/kubeconfig','123456789012')
        native=Native();native.account='999999999999'
        with self.assertRaises(ContractError):_cluster(target,native,'/private/kubeconfig','123456789012')

    @unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'actual reviewed Go binary required')
    def test_actual_go_fresh_resolver_absence_is_successful_inventory_not_cli_failure(self):
        from test_authorization import AuthorizationTests
        harness=AuthorizationTests();harness.setUp();prepared=harness.prepared()
        prepared.plan=preview_plan();prepared._backend=copy.deepcopy(harness.context['backend'])
        prepared._module_origin=lambda _:copy.deepcopy(harness.context['origin'])
        prepared.lifecycle=copy.deepcopy(harness.context['lifecycle'])
        prepared.lifecycle.update(refClass='preview',deploymentName='pull_request/prod',protectedEnvironment='pull_request/prod')
        prepared.store=SimpleNamespace(entries=lambda:[])
        prepared._bound=True
        target=prepared.plan['targets'][0]
        class Native:
            def __init__(self):self.calls=[];self.fail=False
            def run(self,argv,**kwargs):
                self.calls.append((argv,kwargs))
                if 'projects' in argv:value={'projectId':target['project'],'projectNumber':'123456789012'}
                elif 'clusters' in argv:value={'name':target['cluster'],'selfLink':'https://container.googleapis.com/v1/projects/'+target['project']+'/locations/'+target['location']+'/clusters/'+target['cluster'],
                    'endpoint':'cluster.example','masterAuth':{'clusterCaCertificate':'ca'}}
                elif 'namespaces' in argv:value={'items':[{'metadata':{'name':'ingress'}}]}
                elif 'config' in argv:value={'current-context':'trusted','contexts':[{'name':'trusted','context':{'cluster':'cluster'}}],
                    'clusters':[{'name':'cluster','cluster':{'server':'https://cluster.example','certificate-authority-data':'ca'}}]}
                else:return subprocess.CompletedProcess(argv,1 if self.fail else 0,'','private-error-CANARY')
                return subprocess.CompletedProcess(argv,0,json.dumps(value),'')
        native=Native()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700);kube=root/'kubeconfig';kube.write_text('private');kube.chmod(0o600)
            local=context(prepared,native,target_id=target['id'],pr=42,workdir=root,credentials=prepared._credentials,kubeconfig=kube)
            resolved=local['resolve_preview'](target['id'],'')
            self.assertFalse(resolved['existing']['exists'])
            self.assertTrue(any('/namespace/pr-42-' in c for c in resolved['resourceClaims']))
            self.assertEqual(len(resolved['resourceClaims']),3)
            self.assertNotIn('/namespace/normal',resolved['resourceClaims'][0])
            native.fail=True
            from executor import ExecutionError
            with self.assertRaises(ExecutionError):local['resolve_preview'](target['id'],'')
            self.assertFalse(any('CANARY' in str(v) for v in resolved.values()))
            self.assertFalse(any(argv[0] in ('tofu','terragrunt') for argv,_ in native.calls))


if __name__=='__main__':unittest.main()
