"""Offline characterization of eight immutable, pre-existing deployment modules.

These tests verify captured source contracts and Git-object provenance, not HCL
evaluation, provider schemas/plans, cloud capability or safe component reuse.
Capture uses local Git objects, never module working trees. Running tests needs
only Python's standard library, this file and its checked-in evidence fixture.
"""

import hashlib
import json
from pathlib import Path
import re
import unittest


FIXTURE = Path(__file__).with_name('fixtures') / 'iac_capabilities' / 'aws_gcp_source.json'
PINS = {
    'aws-eks': ('aws-eks-helm', 'v5.8.3',
                'bcbc8ed33108f64f64ced3ccff7505d134283426',
                'f7931ad99cd0d805ef73ea1d3b5d4eacfef59247'),
    'aws-beanstalk': ('aws-elasticbeanstalk', 'v5.2.0',
                      '04a82af7515d2fdb77540cb5ffad2aa3a97d0266',
                      '753eba6ec6fcfeb6f99f5337eeaa59627df93d94'),
    'aws-lambda': ('aws-lambda', 'v5.5.0',
                   'c5af0e0a720f1edf81da5a249007d9d3e6704b85',
                   '34eae4ea8617b76e2d6cd500d59df0688cc33e22'),
    'aws-s3-static': ('aws-s3-static-content', 'v1.0.3',
                      'be52f21b75347d5c7c87efa195de4deab0d76355',
                      '0aa8154f6eb2a13fa7ec45d82d1083526e911099'),
    'aws-api-gateway': ('aws-api-gateway-apis', 'v6.0.26',
                        '22954e2af23d8cbd118a004709c7d04db96b5d0d',
                        '4c6ee063c3c55682febcb909232dba0860660500'),
    'gcp-gke': ('gcp-gke-helm', 'v2.0.0',
                '1341f8613a3f7fed7657f16ccd6eee8a98a96243',
                '6b426c704639196c6a9b21d4bc5358646dbbc012'),
    'gcp-cloudrun': ('gcp-cloudrun', 'v1.0.3',
                     '2e818a64e02774a407384f4110fcd615025c05e1',
                     'd90f544730b4db1050085d2cc2e4ec9832646833'),
    'gcp-appengine': ('gcp-appengine', 'v1.0.4',
                      '4d2199f29448c99b9d44d81bc2575f763d31a4a8',
                      '4009948af86aa6444f20dceac8c580f87d905a75'),
}


def git_object_id(kind, content):
    raw = content.encode('utf-8') if isinstance(content, str) else content
    return hashlib.sha1(f'{kind} {len(raw)}\0'.encode() + raw).hexdigest()


class PinnedModuleSourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(FIXTURE.read_text())
        cls.modules = {item['id']: item for item in cls.evidence['modules']}

    def source(self, module_id, path, *, active=False):
        source = next(item['content'] for item in self.modules[module_id]['sources']
                      if item['path'] == path)
        if active:
            # Sufficient only for captured line-level declarations; not an HCL parser.
            return '\n'.join(line for line in source.splitlines()
                             if not line.lstrip().startswith('#'))
        return source

    def declarations(self, module_id, kind='resource'):
        return {item['type'] for item in self.modules[module_id]['contracts']
                ['direct_declarations'][kind]}

    def test_fixture_is_bounded_source_evidence_not_reuse_or_cloud_authority(self):
        self.assertLess(FIXTURE.stat().st_size, 512 * 1024)
        self.assertEqual(self.evidence['schema_version'], 1)
        self.assertEqual(self.evidence['evidence_level'], 'source-inspection')
        self.assertFalse(self.evidence['reuse_authorized'])
        self.assertIn('no provider schema, plan, cloud API', self.evidence['evidence_scope'])
        for module in self.modules.values():
            for key in ('owned_children', 'external_parents', 'modes', 'artifacts',
                        'resource_ownership', 'role_ownership', 'gaps'):
                self.assertTrue(module['contracts'][key], (module['id'], key))

    def test_all_eight_catalog_pins_keep_tag_objects_distinct_from_commits(self):
        self.assertEqual(set(self.modules), set(PINS))
        self.assertEqual(len(self.evidence['modules']), 8)
        for identifier, (name, ref, tag, commit) in PINS.items():
            with self.subTest(module=identifier):
                module = self.modules[identifier]
                self.assertEqual(module['repository_url'],
                                 f'https://github.com/cloudopsworks/terraform-module-{name}-deploy.git')
                self.assertEqual((module['ref'], module['tag_object'], module['peeled_commit']),
                                 (ref, tag, commit))
                self.assertNotEqual(tag, commit)

    def test_raw_annotated_tags_and_commits_reproduce_recorded_git_identities(self):
        for module in self.modules.values():
            with self.subTest(module=module['id']):
                tag = module['tag_object_content']
                self.assertEqual(git_object_id('tag', tag), module['tag_object'])
                self.assertTrue(tag.startswith(f"object {module['peeled_commit']}\ntype commit\n"))
                self.assertIn(f"\ntag {module['ref']}\n", tag)
                self.assertEqual(git_object_id('commit', module['commit_object_content']),
                                 module['peeled_commit'])

    def test_full_source_content_reproduces_git_blob_and_sha256(self):
        for module in self.modules.values():
            paths = set()
            for source in module['sources']:
                with self.subTest(module=module['id'], path=source['path']):
                    self.assertNotIn(source['path'], paths)
                    paths.add(source['path'])
                    self.assertNotIn('..', Path(source['path']).parts)
                    self.assertEqual(git_object_id('blob', source['content']), source['git_blob'])
                    self.assertEqual(hashlib.sha256(source['content'].encode()).hexdigest(),
                                     source['sha256'])
            self.assertTrue({'main.tf', 'versions.tf'}.issubset(paths))

    def test_commit_tree_cryptographically_links_all_captured_root_tf_blobs(self):
        for module in self.modules.values():
            with self.subTest(module=module['id']):
                tree = module['root_tree_object']
                raw = bytes.fromhex(tree['content_hex'])
                self.assertEqual(git_object_id('tree', raw), tree['oid'])
                self.assertTrue(module['commit_object_content'].startswith(f"tree {tree['oid']}\n"))
                entries = {}
                while raw:
                    end = raw.index(b'\0')
                    mode, name = raw[:end].split(b' ', 1)
                    oid = raw[end + 1:end + 21]
                    self.assertEqual(len(oid), 20)
                    if mode == b'100644' and name.endswith(b'.tf'):
                        entries[name.decode()] = oid.hex()
                    raw = raw[end + 21:]
                self.assertEqual(entries, {item['path']: item['git_blob']
                                           for item in module['sources']})

    def test_excerpts_and_direct_ownership_inventory_point_to_actual_lines(self):
        for module in self.modules.values():
            sources = {source['path']: source for source in module['sources']}
            for source in sources.values():
                lines = source['content'].splitlines()
                for excerpt in source['excerpts']:
                    self.assertEqual('\n'.join(lines[excerpt['start_line'] - 1:excerpt['end_line']]),
                                     excerpt['text'])
            for kind, declarations in module['contracts']['direct_declarations'].items():
                for declaration in declarations:
                    line = sources[declaration['path']]['content'].splitlines()[declaration['line'] - 1]
                    prefix = f'{kind} "{declaration["type"]}"' if kind != 'module' else 'module'
                    self.assertTrue(line.startswith(f'{prefix} "{declaration["name"]}"'))

    def test_eks_and_gke_own_releases_and_optional_namespace_not_the_cluster(self):
        for identifier in ('aws-eks', 'gcp-gke'):
            with self.subTest(module=identifier):
                resources = self.declarations(identifier)
                self.assertTrue({'helm_release', 'kubernetes_namespace',
                                 'kubernetes_labels', 'kubernetes_annotations'}.issubset(resources))
                self.assertFalse({'aws_eks_cluster', 'google_container_cluster'} & resources)
                main = self.source(identifier, 'main.tf', active=True)
                self.assertIn('count = var.create_namespace ? 1 : 0', main)
                self.assertIn('count = var.create_namespace ? 0 : 1', main)
                self.assertIn('data "kubernetes_namespace" "this"', main)

    def test_beanstalk_delegates_version_environment_and_dns_beyond_direct_inventory(self):
        main = self.source('aws-beanstalk', 'main.tf', active=True)
        for child, version in (('beanstalk-version', '1.6.1'),
                               ('beanstalk-deploy', '1.2.0'), ('beanstalk-dns', '1.1.0')):
            self.assertIn(f'"cloudopsworks/{child}/aws"', main)
            self.assertRegex(main, r'version\s*=\s*"' + re.escape(version) + '"')
        self.assertIn('var.beanstalk.application', main)
        self.assertIn('var.versions_bucket', main)
        self.assertIn('var.beanstalk.iam.instance_profile', main)
        self.assertIn('transitive', ' '.join(self.modules['aws-beanstalk']['contracts']['gaps']))

    def test_lambda_zip_is_s3_backed_and_does_not_implement_image_mode(self):
        main = self.source('aws-lambda', 'main.tf', active=True)
        self.assertRegex(main, r'package_type\s*=\s*"Zip"')
        self.assertRegex(main, r's3_bucket\s*=\s*var.versions_bucket')
        self.assertRegex(main, r's3_key\s*=\s*var.bucket_path')
        self.assertNotRegex(main, r'\bimage_uri\s*=|package_type\s*=\s*"Image"')
        self.assertEqual(self.modules['aws-lambda']['contracts']['modes'], ['Zip'])

    def test_lambda_same_path_zip_has_no_active_content_hash_or_object_version_input(self):
        raw = self.source('aws-lambda', 'main.tf')
        active = self.source('aws-lambda', 'main.tf', active=True)
        self.assertIn('#source_code_hash = base64sha256(', raw)
        self.assertNotRegex(active, r'\b(source_code_hash|s3_object_version)\s*=')
        # Absence establishes a source gap, not a fabricated same-path provider plan.
        self.assertIn('not an observed provider plan',
                      ' '.join(self.modules['aws-lambda']['contracts']['gaps']))

    def test_lambda_owns_iam_and_can_mutate_existing_bucket_notifications(self):
        resources = self.declarations('aws-lambda')
        self.assertTrue({'aws_iam_role', 'aws_iam_policy', 'aws_iam_role_policy',
                         'aws_iam_role_policy_attachment', 'aws_s3_bucket_notification',
                         'aws_cloudwatch_log_group'}.issubset(resources))
        self.assertIn('aws_s3_bucket', self.declarations('aws-lambda', 'data'))
        self.assertNotIn('aws_s3_bucket', resources)

    def test_static_s3_upload_owns_objects_not_bucket_and_uses_file_md5(self):
        self.assertEqual(self.declarations('aws-s3-static'), {'aws_s3_object'})
        self.assertIn('aws_s3_bucket', self.declarations('aws-s3-static', 'data'))
        main = self.source('aws-s3-static', 'main.tf', active=True)
        self.assertIn('each.value.digests.md5', main)
        self.assertIn('var.s3.prefix', main)

    def test_api_module_can_own_whole_apis_stages_and_shared_associations(self):
        resources = self.declarations('aws-api-gateway')
        self.assertTrue({'aws_api_gateway_rest_api', 'aws_apigatewayv2_api',
                         'aws_api_gateway_stage', 'aws_apigatewayv2_stage',
                         'aws_lambda_permission', 'aws_wafv2_web_acl_association'}.issubset(resources))
        self.assertIn('aws_api_gateway_rest_api', self.declarations('aws-api-gateway', 'data'))
        versions = self.source('aws-api-gateway', 'versions.tf', active=True)
        self.assertIn('"hashicorp/aws"', versions)
        self.assertIn('"~> 6.4"', versions)
        self.assertIn('"hashicorp/local"', versions)

    def test_cloudrun_uses_version_tag_and_creates_identity_and_project_roles(self):
        main = self.source('gcp-cloudrun', 'main.tf', active=True)
        self.assertIn('format("%s/%s/%s:%s", var.container_registry, var.repository_owner, var.release.name, var.release.source.version)', main)
        resources = self.declarations('gcp-cloudrun')
        self.assertTrue({'google_cloud_run_v2_service', 'google_service_account',
                         'google_project_iam_member', 'google_service_account_iam_binding'}.issubset(resources))
        self.assertIn('"roles/artifactregistry.writer"', self.source('gcp-cloudrun', 'iam.tf'))

    def test_appengine_standard_zip_is_active_flex_and_container_are_not(self):
        raw = self.source('gcp-appengine', 'main.tf')
        active = self.source('gcp-appengine', 'main.tf', active=True)
        self.assertIn('google_app_engine_standard_app_version', self.declarations('gcp-appengine'))
        self.assertNotIn('google_app_engine_flexible_app_version', self.declarations('gcp-appengine'))
        self.assertIn('# resource "google_app_engine_flexible_app_version"', raw)
        self.assertIn('local.engine_standard ? 1 : 0', active)
        self.assertIn('"standard") == "standard"', active)
        self.assertIn('https://storage.googleapis.com/${var.versions_bucket}/${var.bucket_path}', active)
        self.assertNotRegex(active, r'\b(container|image)\s*[={]')
        self.assertIn('delete_service_on_destroy = true', active)

    def test_google_beta_requirement_does_not_establish_beta_api_execution(self):
        for identifier in ('gcp-gke', 'gcp-cloudrun', 'gcp-appengine'):
            with self.subTest(module=identifier):
                versions = self.source(identifier, 'versions.tf', active=True)
                self.assertIn('"hashicorp/google-beta"', versions)
                self.assertIn('"hashicorp/google"', versions)
                self.assertIn('"~> 7.0"', versions)
        main = self.source('gcp-appengine', 'main.tf', active=True)
        self.assertNotRegex(main, r'provider\s*=\s*google-beta')

    def test_appengine_owns_bucket_and_project_iam_not_only_a_version_child(self):
        self.assertTrue({'google_service_account', 'google_project_iam_member',
                         'google_storage_bucket_iam_binding',
                         'google_service_account_iam_binding'}.issubset(self.declarations('gcp-appengine')))
        iam = self.source('gcp-appengine', 'iam.tf', active=True)
        for role in ('compute.networkUser', 'logging.logWriter', 'artifactregistry.writer',
                     'storage.objectAdmin', 'iam.serviceAccountUser'):
            self.assertIn(f'"roles/{role}"', iam)
        self.assertNotIn('google_app_engine_application', self.declarations('gcp-appengine'))


if __name__ == '__main__':
    unittest.main()
