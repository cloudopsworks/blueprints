"""Pinned AWS remaining-root local proof; no provider Apply or cloud readiness claim."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "terraform/monorepo/modules"
NAMES = ("aws-beanstalk", "aws-s3-static", "aws-apigateway-rest")
FIXTURE = ROOT / "tests/monorepo/fixtures/iac_capabilities/aws_roots_source_operations.json"


class AwsRemainingRootTests(unittest.TestCase):
    def command(self, directory, *arguments, env=None):
        result = subprocess.run(["tofu", *arguments], cwd=directory, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"{arguments}:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def test_exact_provider_validate_and_mock_lifecycle(self):
        self.assertEqual(json.loads(self.command(ROOT, "version", "-json"))["terraform_version"], "1.11.4")
        plugins = (ROOT / "terraform/monorepo/capabilities/.terraform/providers").resolve()
        self.assertTrue(plugins.is_dir(), "Exact selected provider cache must be initialized")
        with tempfile.TemporaryDirectory(prefix="aws-remaining-roots-") as temporary:
            for name in NAMES:
                with self.subTest(root=name):
                    destination = Path(temporary) / name
                    shutil.copytree(MODULES / name, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
                    self.command(destination, "fmt", "-check", "-recursive")
                    self.command(destination, "init", "-backend=false", "-input=false", "-lockfile=readonly", f"-plugin-dir={plugins}")
                    self.command(destination, "validate", "-no-color")
                    schema = json.loads(self.command(destination, "providers", "schema", "-json"))
                    selected = schema["provider_schemas"]["registry.opentofu.org/hashicorp/aws"]["resource_schemas"]
                    self.assertTrue(selected["aws_api_gateway_rest_api"]["block"]["attributes"]["name"]["required"])
                    self.assertNotIn("version", selected["aws_api_gateway_rest_api"]["block"]["attributes"])
                    self.assertIn("source_hash", selected["aws_s3_object"]["block"]["attributes"])
                    output = self.command(destination, "test", "-no-color")
                    self.assertIn("0 failed", output)
                    self.assertIn('run "owned_mock_apply"... pass', output)

    def test_actual_provider_offline_api_plan_exact_body_and_trigger(self):
        """Real AWS PlanResourceChange, fake explicit credentials, no data reads/apply."""
        plugins = (ROOT / "terraform/monorepo/capabilities/.terraform/providers").resolve()
        with tempfile.TemporaryDirectory(prefix="aws-api-offline-") as temporary:
            destination = Path(temporary) / "root"
            shutil.copytree(MODULES / "aws-apigateway-rest", destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
            (destination / "offline_override.tf").write_text('''provider "aws" {
 region = var.resource.region
 access_key = "offline-not-a-credential"
 secret_key = "offline-not-a-credential"
 skip_credentials_validation = true
 skip_requesting_account_id = true
 skip_metadata_api_check = true
 skip_region_validation = true
}''')
            env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
            env.update(AWS_EC2_METADATA_DISABLED="true", AWS_SHARED_CREDENTIALS_FILE="/dev/null", AWS_CONFIG_FILE="/dev/null")
            self.command(destination, "init", "-backend=false", "-input=false", "-lockfile=readonly", f"-plugin-dir={plugins}", env=env)
            inputs = json.loads((destination / "tests/fixtures/inputs.json").read_text())
            for iteration in range(2):
                if iteration:
                    source = destination / inputs["artifact"]["path"]
                    source.write_text(source.read_text().replace('version: "1"', 'version: "2"'))
                    inputs["artifact"]["digest"] = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
                values = destination / "operation.tfvars.json"
                values.write_text(json.dumps(inputs))
                self.command(destination, "plan", "-refresh=false", "-input=false", "-no-color", "-var-file=operation.tfvars.json", "-out=reviewed.plan", env=env)
                plan = json.loads(self.command(destination, "show", "-json", "reviewed.plan", env=env))
                changes = {item["address"]: item["change"] for item in plan["resource_changes"]}
                self.assertEqual(set(changes), {"aws_api_gateway_rest_api.component", "aws_api_gateway_deployment.component", "aws_api_gateway_stage.component"})
                self.assertEqual(changes["aws_api_gateway_rest_api.component"]["after"]["body"], (destination / inputs["artifact"]["path"]).read_text())
                trigger = changes["aws_api_gateway_deployment.component"]["after"]["triggers"]
                self.assertEqual(trigger["artifact"], inputs["artifact"]["digest"])
                self.assertEqual(trigger["specification"], inputs["artifact"]["digest"][7:])
                self.assertTrue(all(change["actions"] == ["create"] for change in changes.values()))

    def test_exact_source_operations_and_external_parent_boundary(self):
        evidence = json.loads(FIXTURE.read_text())
        self.assertEqual(evidence["providerVersion"], "6.35.0")
        self.assertEqual(evidence["commit"], "5225b5f3abef80b0cdfcb2634d367aba6edd5261")
        expected = {
            "solution_stack_data_source.go": ["ListAvailableSolutionStacks(ctx", "name_regex"],
            "delete.go": ["DeleteObject(ctx", "DeleteObjects(ctx"],
            "application_version.go": ["CreateApplicationVersion(ctx", "DeleteApplicationVersion(ctx"],
            "environment.go": ["CreateEnvironment(ctx", "UpdateEnvironment(ctx", "TerminateEnvironment(ctx"],
            "object.go": ["source_hash", "ContentType", "deleteObjectVersion(ctx", "deleteAllObjectVersions(ctx"],
            "rest_api.go": ["CreateRestApi(ctx", "PutRestApi(ctx", "DeleteRestApi(ctx"],
            "deployment.go": ["CreateDeployment(ctx", "DeleteDeployment(ctx"],
            "stage.go": ["CreateStage(ctx", "UpdateStage(ctx", "DeleteStage(ctx"],
        }
        for source in evidence["sources"]:
            self.assertIn("/" + evidence["commit"] + "/", source["url"])
            self.assertEqual(hashlib.sha256(source["content"].encode()).hexdigest(), source["sha256"])
            for operation in expected[Path(source["path"]).name]:
                self.assertIn(operation, source["content"])
        for name in NAMES:
            root = MODULES / name
            metadata = json.loads((root / "inputs.json").read_text())
            self.assertTrue(metadata["activationBlocked"])
            text = "\n".join(path.read_text() for path in root.glob("*.tf"))
            declared = re.findall(r'resource\s+"([^"]+)"', text)
            self.assertEqual(set(declared), set(metadata["ownedResourceTypes"]))
            self.assertFalse(set(declared) & {"aws_s3_bucket", "aws_iam_role", "aws_vpc", "aws_subnet", "aws_elastic_beanstalk_application", "aws_api_gateway_account", "aws_api_gateway_domain_name"})
            self.assertNotRegex(text, r'\b(provisioner|local-exec|import)\s*["{]')
            self.assertEqual((root / "terragrunt.hcl").read_text().splitlines()[-1], "terraform {}")


if __name__ == "__main__":
    unittest.main()
