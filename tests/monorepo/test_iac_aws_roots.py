"""AWS Lambda root/source proof; real provider plans are separate tofu test.

This does not activate the root or claim credentialed workload execution.
"""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from iac import module_tree, verify_saved_plan, IaCError
MODULE=ROOT/'terraform/monorepo/modules/aws-lambda'


class AWSRootTests(unittest.TestCase):
    def test_module_tree_provider_lock_and_honest_activation_gate(self):
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        row=catalog['modules']['aws-lambda'];self.assertTrue(row['activationBlocked'])
        self.assertEqual(row['revision'],module_tree(MODULE,row['files']))
        self.assertEqual(row['providerLockDigest'],'sha256:'+hashlib.sha256((MODULE/'.terraform.lock.hcl').read_bytes()).hexdigest())
        self.assertIn('version = "= 6.35.0"',(MODULE/'versions.tf').read_text())
        self.assertEqual(set(json.loads((MODULE/'inputs.json').read_text())['ownedResourceTypes']),{'aws_lambda_function','aws_lambda_alias','aws_s3_object'})

    def test_no_parent_declarations_importers_hooks_or_sdk_fallback(self):
        text=(MODULE/'main.tf').read_text()
        self.assertIn('data "aws_iam_role"',text);self.assertIn('data "aws_s3_bucket"',text)
        for forbidden in ('resource "aws_iam_role"','resource "aws_s3_bucket"','resource "aws_ecr_repository"','provisioner ','local-exec','import {'):
            self.assertNotIn(forbidden,text)
        self.assertEqual((MODULE/'terragrunt.hcl').read_text().strip().splitlines()[-1],'terraform {}')
        self.assertIn('filebase64sha256(local.package_path)',text)
        self.assertIn('filesha256(local.package_path)',text)
        self.assertIn('s3_object_version',text);self.assertRegex(text,r'publish\s*= true')

    def test_selected_provider_source_create_update_delete_and_digest_paths(self):
        value=json.loads((Path(__file__).parent/'fixtures/iac_capabilities/aws_lambda_provider_source.json').read_text())
        self.assertEqual(value['commit'],'5225b5f3abef80b0cdfcb2634d367aba6edd5261')
        source=value['sources'][0];text=source['content']
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),source['sha256'])
        self.assertIn('/'+value['commit']+'/',source['url'])
        for path in ('resourceFunctionCreate','resourceFunctionUpdate','resourceFunctionDelete','CreateFunction(ctx','UpdateFunctionCode(ctx','DeleteFunction(ctx','input.ImageUri','input.S3ObjectVersion','source_code_hash'):
            self.assertTrue(path in text, path)
        self.assertTrue('needsFunctionCodeUpdate(d)' in text)
        self.assertIn('"image_uri"',text)

    def test_function_parent_or_package_mode_replacement_never_implicit(self):
        for address,actions in (('aws_iam_role.parent',['create']),('aws_lambda_function.component',['delete','create'])):
            with self.assertRaises(IaCError):
                verify_saved_plan({'resource_changes':[{'mode':'managed','address':address,'change':{'actions':actions}}]},operation='apply',addresses=['aws_lambda_function.component'],owner_digest='owner',previously_owned={'aws_lambda_function.component'})


if __name__=='__main__':unittest.main()
