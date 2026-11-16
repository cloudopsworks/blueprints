"""Pinned Kubernetes root proof; mocks do not establish cluster/CNI activation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from iac import execution_tree, IaCError

MODULE=ROOT/'terraform/monorepo/modules/kubernetes-component'


class KubernetesRootTests(unittest.TestCase):
    def test_authoritative_chart_and_exact_three_family_binding(self):
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        for name in ('aws-eks','gcp-gke','azure-aks'):
            row=catalog['modules'][name]
            self.assertEqual(row['path'],'terraform/monorepo/modules/kubernetes-component')
            self.assertEqual(row['chartPath'],'kubernetes/helm/charts')
            self.assertEqual(execution_tree(ROOT,row),row['revision'])
            self.assertEqual(row['providerLockDigest'],'sha256:'+hashlib.sha256((MODULE/'.terraform.lock.hcl').read_bytes()).hexdigest())
        row=dict(row,chartPath='untrusted/alternate-chart')
        with self.assertRaises(IaCError):execution_tree(ROOT,row)
        text=(MODULE/'main.tf').read_text()
        self.assertIn('data "kubernetes_namespace_v1" "external"',text)
        self.assertNotIn('resource "kubernetes_namespace_v1"',text)
        for forbidden in ('local-exec','provisioner ', 'import {'):
            self.assertNotIn(forbidden,text)

    def test_exact_tools_provider_validation_and_mock_saved_workloads(self):
        tofu=shutil.which('tofu');self.assertIsNotNone(tofu,'Exact OpenTofu is required')
        self.assertEqual(json.loads(subprocess.check_output([tofu,'version','-json']))['terraform_version'],'1.11.4')
        tg=Path('/tmp/terragrunt-v511-0.99.4')
        self.assertTrue(tg.is_file(),'SHA-verified Terragrunt fixture binary is required')
        self.assertEqual(hashlib.sha256(tg.read_bytes()).hexdigest(),'5b33dec8e3e720347732713a4f5a7d3fed70c0c87771c38943dd59ef4fa3f055')
        plugins=Path(os.environ.get('TOFU_PLUGIN_DIR',ROOT/'terraform/monorepo/capabilities/.terraform/providers')).resolve()
        with tempfile.TemporaryDirectory(prefix='kubernetes-root-tests-') as temporary:
            # Keep the authoritative chart reference, never copy/fork it.
            destination=Path(temporary)/'component'
            shutil.copytree(MODULE,destination,ignore=shutil.ignore_patterns('.terraform','*.tfstate*'))
            test=destination/'tests/roots.tftest.hcl'
            test.write_text(test.read_text().replace('"../../../../kubernetes/helm/charts"',json.dumps(str(ROOT/'kubernetes/helm/charts'))))
            for arguments in (['fmt','-check','-recursive'],['init','-backend=false','-input=false','-lockfile=readonly',f'-plugin-dir={plugins}'],['validate','-no-color']):
                completed=subprocess.run([tofu,*arguments],cwd=destination,text=True,capture_output=True)
                self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            env=dict(os.environ,TG_TF_PATH=tofu)
            completed=subprocess.run([str(tg),'--non-interactive','--working-dir',str(destination),'run','--','test','-no-color'],env=env,text=True,capture_output=True)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            self.assertIn('6 passed, 0 failed',completed.stdout)

    def test_namespace_and_manifest_name_only_deletion_cannot_prove_uid_guard(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/iac_capabilities/kubernetes_delete_source.json').read_text())
        self.assertEqual(fixture['version'],'2.38.0')
        self.assertIn('source-only',fixture['evidenceScope'])
        for source in fixture['sources']:
            self.assertEqual(hashlib.sha256(source['content'].encode()).hexdigest(),source['sha256'])
            self.assertIn('/v2.38.0/',source['url'])
            self.assertRegex(source['content'],r'\.Delete\([^\n]*metav1.DeleteOptions\{\}\)')
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        for name in ('aws-preview-environment','gcp-preview-environment','azure-preview-environment'):
            self.assertTrue(catalog['modules'][name]['activationBlocked'])


if __name__=='__main__':unittest.main()
