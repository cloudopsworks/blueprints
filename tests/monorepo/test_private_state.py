import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from private_state import read_private_state
from contracts import ContractError

class Transport:
    def __init__(self,kind):self.kind=kind;self.calls=[];self.payload=b'{"version":4,"resources":[]}';self.fail=False;self.too_large=False
    def run(self,argv,**kwargs):
        self.calls.append((argv,kwargs))
        if self.fail:return SimpleNamespace(returncode=1,stdout='',stderr='secret-state-sentinel')
        size=100000000 if self.too_large else len(self.payload)
        if 'head-object' in argv:value={'ContentLength':size,'ETag':'"fixed-etag"'}
        elif 'describe' in argv:value={'size':str(size),'generation':'42'}
        elif 'show' in argv:value={'properties':{'contentLength':size,'etag':'"fixed-etag"'}}
        else:
            if 'get-object' in argv:path=Path(argv[argv.index('--if-match')+2])
            elif argv[:3]==['gcloud','storage','cp']:path=Path(argv[4])
            else:path=Path(argv[argv.index('--file')+1])
            path.write_bytes(self.payload);value={}
        return SimpleNamespace(returncode=0,stdout=json.dumps(value),stderr='')

class PrivateStateTests(unittest.TestCase):
    def handles(self):
        handle=json.loads((Path(__file__).parent/'fixtures/operations/state-handle.json').read_text())
        yield 's3',handle
        handle=copy.deepcopy(handle);handle['backend']={'kind':'gcs','bucket':'state-example','prefix':'deployments/frozen','workspace':'blue'};handle['native']={'stateAddress':'gs://state-example/deployments/frozen/blue.tfstate','lockAddress':'gs://state-example/deployments/frozen/blue.tflock','dynamodbLockId':None,'leaseMetadataKey':None}
        yield 'gcs',handle
        handle=copy.deepcopy(handle);handle['backend']={'kind':'azurerm','resourceGroupName':'rg','storageAccountName':'stateaccount','containerName':'state','key':'frozen','workspace':'default','useOidc':True,'useAzureadAuth':True,'tenantIdRef':'tenant','subscriptionIdRef':'subscription','clientIdRef':'client'};handle['native']={'stateAddress':'https://stateaccount.blob.core.windows.net/state/frozen','lockAddress':None,'dynamodbLockId':None,'leaseMetadataKey':'terraformlockid'}
        yield 'azurerm',handle
    def test_all_three_conditional_bounded_private_reads_no_init_or_lock_mutation(self):
        for kind,handle in self.handles():
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                if kind!='s3':
                    handle['backend']={key:value for key,value in handle['backend'].items() if key not in ('tenantIdRef','clientIdRef','subscriptionIdRef')}
                    handle['backend']['authRef']='backend-reader'
                    handle['authRefs']=sorted(set(handle['authRefs']+['backend-reader']))
                    handle['backendIdentity']=({'provider':'gcp','projectNumber':'987654321'} if kind=='gcs' else
                        {'provider':'azure','tenantId':'11111111-1111-1111-1111-111111111111','subscriptionId':'22222222-2222-2222-2222-222222222222'})
                ex=Transport(kind);state=read_private_state(handle,ex,workdir=directory,env={'PATH':'/trusted'})
                self.assertEqual(state,{'version':4,'resources':[]})
                self.assertEqual(len(ex.calls),2)
                command=ex.calls[1][0]
                self.assertTrue('--if-match' in command or '#42' in command[3])
                self.assertFalse(list(Path(directory).iterdir()))
    def test_oversize_failure_and_mutated_bytes_are_not_missing_state(self):
        handle=next(self.handles())[1]
        for mutation in ('too_large','fail','payload'):
            ex=Transport('s3');setattr(ex,mutation,b'invalid-secret-state-sentinel' if mutation=='payload' else True)
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(Exception) as caught:
                read_private_state(handle,ex,workdir=directory,env={})
            self.assertNotIn('sentinel',str(caught.exception))
if __name__=='__main__':unittest.main()
