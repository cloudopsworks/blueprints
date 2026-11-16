"""P0 completeness/negative-scope checks, not execution-root acceptance."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKBENCH = ROOT / "terraform/monorepo/capabilities"
FIXTURES = Path(__file__).parent / "fixtures/iac_capabilities"


class CapabilityLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads((WORKBENCH / "capability-lock.json").read_text())
        cls.configuration = json.loads((WORKBENCH / "main.tf.json").read_text())
        cls.schema = json.loads((FIXTURES / "provider_schema.json").read_text())

    def test_exact_tool_provider_lock_and_fixture_tree(self):
        self.assertEqual(self.lock["tools"]["opentofu"], "1.11.4")
        self.assertEqual(self.lock["tools"]["terragrunt"], "0.99.4")
        self.assertEqual(self.lock["providerLockDigest"], "sha256:" + hashlib.sha256(
            (ROOT / self.lock["providerLockPath"]).read_bytes()).hexdigest())
        h = hashlib.sha256()
        for name in sorted(self.lock["revisionFiles"]):
            h.update(name.encode() + b"\0" + (WORKBENCH / name).read_bytes() + b"\0")
        self.assertEqual(self.lock["capabilityRevision"], "sha256:" + h.hexdigest())
        pins = (WORKBENCH / "versions.tf").read_text()
        lock = (WORKBENCH / ".terraform.lock.hcl").read_text()
        for name, version in self.lock["providers"].items():
            self.assertIn('version = "= ' + version + '"', pins)
            self.assertRegex(lock, r'(?s)provider "registry.opentofu.org/hashicorp/' + re.escape(name) + r'" \{.*?version\s*= "' + re.escape(version) + '"')

    def test_seventeen_families_plus_three_preview_environments_honest_gate(self):
        families = self.lock["families"]
        ids = {r["moduleId"] for r in families}
        self.assertEqual(len(ids), 20)
        self.assertEqual(len([i for i in ids if i.endswith("-preview-environment")]), 3)
        self.assertTrue(self.lock["activationBlocked"])
        for row in families:
            self.assertTrue(row["activationBlocked"])
            self.assertEqual(row["proof"]["plan"], "mock-provider-plan")
            self.assertEqual(row["proof"]["ownership"], "not-implemented")
            self.assertEqual(row["proof"]["live"], "not-run")
            self.assertTrue(row["modes"])
            self.assertTrue(row["externalParents"])
            for address in row["resourceAddresses"]:
                kind, name = address.split(".", 1)
                name = name.split("[", 1)[0]
                self.assertIn(name, self.configuration["resource"][kind])

    def test_parent_resources_and_mutation_escape_hatches_absent(self):
        resources = self.configuration["resource"]
        forbidden = {"aws_iam_role", "aws_s3_bucket", "aws_ecr_repository", "aws_eks_cluster",
                     "google_project", "google_storage_bucket", "google_container_cluster",
                     "google_service_account", "google_app_engine_application", "azurerm_resource_group",
                     "azurerm_service_plan", "azurerm_storage_account", "azurerm_storage_container",
                     "azurerm_user_assigned_identity", "azurerm_role_assignment", "azurerm_api_management",
                     "azurerm_kubernetes_cluster", "azurerm_container_app_environment"}
        self.assertFalse(resources.keys() & forbidden)
        text = json.dumps(self.configuration)
        for escape in ('"provisioner"', '"local-exec"', '"remote-exec"'):
            self.assertNotIn(escape, text)
        self.assertNotIn("backend", self.configuration.get("terraform", {}))
        self.assertIn("data", self.configuration)
        self.assertIn("aws_iam_role", self.configuration["data"])
        self.assertIn("azurerm_service_plan", self.configuration["data"])

    def test_fixed_arm_extensions_and_sensitive_url_no_parent_declarations(self):
        config = self.configuration
        self.assertTrue(config["variable"]["package_read_sas"]["sensitive"])
        self.assertNotIn("output", config)
        feature = config["provider"]["azurerm"]["features"][0]["template_deployment"][0]
        self.assertIs(feature["delete_nested_items_during_deletion"], False)
        for name, deployment in config["resource"]["azurerm_resource_group_template_deployment"].items():
            self.assertEqual(deployment["deployment_mode"], "Incremental")
            template = json.loads(deployment["template_content"])
            self.assertEqual(template["parameters"]["packageUri"]["type"], "securestring")
            self.assertEqual(len(template["resources"]), 1)
            resource = template["resources"][0]
            self.assertIn(resource["type"], {"Microsoft.Web/sites/extensions", "Microsoft.Web/sites/slots/extensions"})
            self.assertTrue(resource["name"].endswith("/onedeploy')]" if name == "onedeploy" else "/ZipDeploy')]"))
            self.assertEqual(resource["properties"]["packageUri"], "[parameters('packageUri')]")
            if name == "onedeploy":
                self.assertIs(resource["properties"]["remoteBuild"], False)
                self.assertNotIn("WEBSITE_RUN_FROM_PACKAGE", config["resource"]["azurerm_function_app_flex_consumption"]["zip"].get("app_settings", {}))
            self.assertIn("azurerm_storage_blob.package", deployment["depends_on"])

    def test_selected_schema_rejects_false_function_slot_zip_route(self):
        azure = self.schema["providers"]["azurerm"]["resources"]
        for os in ("linux", "windows"):
            self.assertIn("zip_deploy_file", azure[f"azurerm_{os}_function_app"]["shape"]["attributes"])
            self.assertNotIn("zip_deploy_file", azure[f"azurerm_{os}_function_app_slot"]["shape"]["attributes"])
        google = self.schema["providers"]["google"]["resources"]
        beta = self.schema["providers"]["google-beta"]["resources"]
        self.assertNotIn("google_api_gateway_api", google)
        self.assertIn("google_api_gateway_api", beta)

    def test_package_fixtures_and_hash_binding(self):
        metadata = json.loads((FIXTURES / "package_bytes.json").read_text())
        digests = []
        for artifact in metadata["artifacts"]:
            content = (FIXTURES / "artifacts" / artifact["path"]).read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            self.assertEqual(digest, artifact["sha256"])
            digests.append(digest)
        self.assertEqual(len(set(digests)), 2)
        blob = self.configuration["resource"]["azurerm_storage_blob"]["package"]
        self.assertEqual(blob["content_md5"], "${filemd5(local.package_path)}")
        self.assertEqual(blob["lifecycle"]["precondition"][0]["condition"], "${filesha256(local.package_path) == var.artifact_digest}")


if __name__ == "__main__":
    unittest.main()
