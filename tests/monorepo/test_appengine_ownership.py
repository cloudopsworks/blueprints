"""Private saved-plan semantics; not cloud inventory or single-writer proof."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from iac import IaCError,verify_appengine_plan

class AppEngineOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.handle={'moduleId':'gcp-appengine','ownership':'managed','resourceIdentity':{'project':'example-project','service':'component','appEnvironment':'standard'}}
        self.address='google_app_engine_standard_app_version.component[0]'
        self.state={'project':'example-project','service':'component','delete_service_on_destroy':True,'noop_on_destroy':False}
    def plan(self, actions, before=True):
        return {'resource_changes':[{'mode':'managed','address':self.address,'change':{'actions':actions,'before':copy.deepcopy(self.state) if before else None,'after':None if actions==['delete'] else copy.deepcopy(self.state)}}]}
    def test_exact_fresh_update_dbc_and_destroy(self):
        for mode in ('standard','flexible'):
            self.handle['resourceIdentity']['appEnvironment']=mode
            self.address='google_app_engine_'+mode+'_app_version.component[0]'
            for actions in (['create'],['update'],['delete','create'],['delete'],['no-op']):
                verify_appengine_plan(self.plan(actions,before=actions!=['create']),self.handle,previously_owned=[] if actions==['create'] else [self.address])
    def test_old_false_unknown_default_cross_mode_and_cbd_rejected(self):
        cases=[]
        for key,value in (('delete_service_on_destroy',False),('noop_on_destroy',True),('project','different'),('service','default')):
            plan=self.plan(['update']);plan['resource_changes'][0]['change']['before'][key]=value;cases.append((plan,self.handle,[self.address]))
        plan=self.plan(['update']);plan['resource_changes'][0]['change']['after_unknown']={'delete_service_on_destroy':True};cases.append((plan,self.handle,[self.address]))
        cases.append((self.plan(['create','delete']),self.handle,[self.address]))
        cases.append((self.plan(['update']),self.handle,['google_app_engine_flexible_app_version.component[0]']))
        handle=copy.deepcopy(self.handle);handle['resourceIdentity']['service']='default';cases.append((self.plan(['create'],False),handle,[]))
        handle=copy.deepcopy(self.handle);handle['ownership']='external';cases.append((self.plan(['create'],False),handle,[]))
        cases.append(({'resource_changes':[]},self.handle,[]))
        for plan,handle,owned in cases:
            with self.subTest(plan=plan),self.assertRaises(IaCError):verify_appengine_plan(plan,handle,previously_owned=owned)
if __name__=='__main__':unittest.main()
