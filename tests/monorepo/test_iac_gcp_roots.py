"""Selected-provider GCP root checks. Mocks prove local plans, never cloud readiness."""
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
NAMES = ("gcp-cloudrun", "gcp-appengine", "gcp-functions-gen2", "gcp-storage-static", "gcp-apigateway")
FIXTURE = ROOT / "tests/monorepo/fixtures/iac_capabilities/gcp_roots_source_operations.json"


class GcpRootTests(unittest.TestCase):
    def test_selected_provider_validation_and_mock_lifecycle(self):
        tofu = shutil.which("tofu")
        self.assertIsNotNone(tofu, "OpenTofu 1.11.4 is required; missing tools are not successful proof")
        version = subprocess.run([tofu, "version", "-json"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(version.stdout)["terraform_version"], "1.11.4")
        plugins = Path(os.environ.get("TOFU_PLUGIN_DIR", ROOT / "terraform/monorepo/capabilities/.terraform/providers"))
        self.assertTrue(plugins.is_dir(), "Initialize the exact capability provider cache before this offline test")
        with tempfile.TemporaryDirectory(prefix="gcp-root-tests-") as temporary:
            for name in NAMES:
                with self.subTest(root=name):
                    destination = Path(temporary) / name
                    shutil.copytree(MODULES / name, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
                    for arguments in (
                        ("fmt", "-check", "-recursive"),
                        ("init", "-backend=false", "-input=false", "-lockfile=readonly", f"-plugin-dir={plugins.resolve()}"),
                        ("validate", "-no-color"),
                        ("test", "-no-color"),
                    ):
                        result = subprocess.run([tofu, *arguments], cwd=destination, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, f"{name} {arguments}:\n{result.stdout}\n{result.stderr}")
                    self.assertIn("0 failed", result.stdout)
                    self.assertIn('owned_mock_apply', result.stdout)

    def test_appengine_real_provider_same_mode_lifecycle(self):
        """Real PlanResourceChange with frozen external reads; never provider Apply."""
        tofu = shutil.which("tofu")
        self.assertIsNotNone(tofu)
        plugins = Path(os.environ.get("TOFU_PLUGIN_DIR", ROOT / "terraform/monorepo/capabilities/.terraform/providers"))
        env = {key: value for key, value in os.environ.items() if not key.startswith(("GOOGLE_", "GCLOUD_", "CLOUDSDK_"))}
        env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9", NO_PROXY="")
        with tempfile.TemporaryDirectory(prefix="appengine-offline-plan-") as temporary:
            directory = Path(temporary)
            shutil.copytree(MODULES / "gcp-appengine", directory, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))

            def run(*arguments):
                result = subprocess.run([tofu, *arguments], cwd=directory, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"{arguments}:\n{result.stdout}\n{result.stderr}")
                return result.stdout

            run("init", "-backend=false", "-input=false", "-lockfile=readonly", f"-plugin-dir={plugins.resolve()}")
            original_main = (directory / "main.tf").read_text()
            events = [json.loads(line) for line in run("test", "-json", "-verbose").splitlines()]
            modes = {event["@testrun"]: event["test_plan"]["variables"] for event in events if event.get("type") == "test_plan"}
            mock_prefix = (directory / "tests/roots.tftest.hcl").read_text().split("variables {", 1)[0]
            for mode in ("standard_native", "flex_native", "flex_oci"):
                with self.subTest(mode=mode):
                    variables = {name: item["value"] for name, item in modes[mode].items()}
                    # Obtain synthetic prior state only through mock Apply. No Google Apply.
                    test = mock_prefix + "\nvariables {\n" + "\n".join(f"{name} = {json.dumps(value)}" for name, value in variables.items()) + '\n}\nrun "prior" { command = apply }\n'
                    (directory / "tests/roots.tftest.hcl").write_text(test)
                    (directory / "main.tf").write_text(original_main)
                    for path in (directory / "offline-provider.tf", directory / "offline.auto.tfvars.json"):
                        path.unlink(missing_ok=True)
                    events = [json.loads(line) for line in run("test", "-json", "-verbose").splitlines()]
                    prior = next(event["test_state"] for event in events if event.get("type") == "test_state")
                    resources = {}
                    for resource in prior["values"]["root_module"]["resources"]:
                        key = (resource["mode"], resource["type"], resource["name"])
                        record = resources.setdefault(key, dict(mode=resource["mode"], type=resource["type"], name=resource["name"], provider='provider["' + resource["provider_name"] + '"]', instances=[]))
                        instance = dict(schema_version=resource["schema_version"], attributes=resource["values"], sensitive_attributes=[])
                        # The JSON state view omits native dependency metadata. Preserve
                        # the root's explicit traffic/version and package edges here.
                        if resource["type"] == "google_app_engine_service_split_traffic":
                            instance["dependencies"] = ["google_app_engine_standard_app_version.component", "google_app_engine_flexible_app_version.component"]
                        elif resource["type"].endswith("app_version"):
                            instance["dependencies"] = ["google_storage_bucket_object.package", "data.google_service_account.external", "data.google_project.external"]
                        if "[" in resource["address"]:
                            instance["index_key"] = 0
                        record["instances"].append(instance)
                    state = dict(version=4, terraform_version="1.11.4", serial=1, lineage="00000000-0000-0000-0000-000000000001", outputs=prior["values"]["outputs"], resources=list(resources.values()))
                    state_path = directory / "terraform.tfstate"
                    state_path.write_text(json.dumps(state))
                    # Freeze only external data resolution. Managed resources use the REAL
                    # selected provider, including ForceNew, not mock_provider semantics.
                    source = original_main
                    for kind, label in (("google_project", "external_project"), ("google_service_account", "external_sa"), ("google_storage_bucket", "external_bucket")):
                        start = source.index(f'data "{kind}" "external"')
                        position = source.index("{", start) + 1
                        depth = 1
                        while depth:
                            depth += (source[position] == "{") - (source[position] == "}")
                            position += 1
                        source = source[:start] + source[position:]
                        source = source.replace(f"data.{kind}.external[0]", f"local.{label}").replace(f"data.{kind}.external", f"local.{label}")
                    source += '\nlocals {\n external_project={project_id="test-project",number="123456789"}\n external_sa={email="runner@test-project.iam.gserviceaccount.com"}\n external_bucket={name="external-bucket",project_number=123456789}\n}\n'
                    (directory / "main.tf").write_text(source)
                    (directory / "offline-provider.tf").write_text('provider "google" {\n access_token="offline-not-a-credential"\n}\n')
                    # Fresh create and historical-state updates both use the ACTUAL
                    # reviewed root. Synthetic state assumes ownership; only the shared
                    # trusted executor can establish history/inventory/exclusivity.
                    version_address = "google_app_engine_" + ("standard" if mode == "standard_native" else "flexible") + "_app_version.component[0]"
                    (directory / "offline.auto.tfvars.json").write_text(json.dumps(variables))
                    state_path.unlink()
                    run("plan", "-refresh=false", "-input=false", "-lock=false", "-out=create.plan")
                    fresh = json.loads(run("show", "-json", "create.plan"))
                    for item in fresh["resource_changes"]:
                        if item["mode"] == "managed":
                            self.assertEqual(item["change"]["actions"], ["create"])
                    created = next(item for item in fresh["resource_changes"] if item["address"] == version_address)["change"]["after"]
                    self.assertTrue(created["delete_service_on_destroy"])
                    self.assertFalse(created["noop_on_destroy"])
                    self.assertEqual(created["service"], "component")
                    state_path.write_text(json.dumps(state))
                    run("plan", "-refresh=false", "-input=false", "-lock=false", "-out=owned.plan")
                    owned = json.loads(run("show", "-json", "owned.plan"))
                    historical = next(item for item in owned["resource_changes"] if item["address"] == version_address)["change"]["before"]
                    self.assertTrue(historical["delete_service_on_destroy"])
                    self.assertFalse(historical["noop_on_destroy"])
                    artifact = variables["artifact"]
                    if mode == "flex_oci":
                        artifact["digest"] = "sha256:" + "e" * 64
                        artifact["imageReference"] = "us-docker.pkg.dev/test-project/images/app@" + artifact["digest"]
                    else:
                        artifact["path"] = str(directory / "tests/changed-package.zip")
                        artifact["digest"] = "sha256:" + hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()
                    (directory / "offline.auto.tfvars.json").write_text(json.dumps(variables))
                    run("plan", "-refresh=false", "-input=false", "-lock=false", "-out=updated.plan")
                    plan = json.loads(run("show", "-json", "updated.plan"))
                    changes = [item for item in plan["resource_changes"] if item["mode"] == "managed"]
                    replacement = next(item for item in changes if item["address"] == version_address)["change"]
                    self.assertEqual(replacement["actions"], ["delete", "create"])
                    for phase in ("before", "after"):
                        self.assertTrue(replacement[phase]["delete_service_on_destroy"])
                        self.assertFalse(replacement[phase]["noop_on_destroy"])
                        self.assertEqual(replacement[phase]["project"], "test-project")
                        self.assertEqual(replacement[phase]["service"], "component")
                    graph = run("graph", "-type=apply", "-plan=updated.plan")
                    edges = {}
                    for dependent, prerequisite in re.findall(r'"(\[root\] [^"]+)" -> "(\[root\] [^"]+)"', graph):
                        edges.setdefault(dependent, set()).add(prerequisite)

                    def requires(dependent, prerequisite):
                        pending, visited = [dependent], set()
                        while pending:
                            current = pending.pop()
                            if current == prerequisite:
                                return True
                            if current not in visited:
                                visited.add(current)
                                pending.extend(edges.get(current, ()))
                        return False

                    self.assertTrue(requires(f"[root] {version_address}", f"[root] {version_address} (destroy)"))
                    self.assertTrue(requires("[root] google_app_engine_service_split_traffic.component (expand)", f"[root] {version_address}"))
                    run("plan", "-destroy", "-refresh=false", "-input=false", "-lock=false", "-out=destroy.plan")
                    destroy = json.loads(run("show", "-json", "destroy.plan"))
                    for item in destroy["resource_changes"]:
                        if item["mode"] == "managed":
                            self.assertEqual(item["change"]["actions"], ["delete"])
                            self.assertIn(item["type"], {"google_app_engine_standard_app_version", "google_app_engine_flexible_app_version", "google_app_engine_service_split_traffic", "google_storage_bucket_object"})
                    # Start the next mode with no persisted synthetic state or real-provider config.
                    state_path.unlink()
                    (directory / "terraform.tfstate.backup").unlink(missing_ok=True)

    def test_owned_addresses_exclude_external_parents_and_shell_execution(self):
        forbidden = {"google_project", "google_storage_bucket", "google_service_account", "google_app_engine_application"}
        for name in NAMES:
            with self.subTest(root=name):
                directory = MODULES / name
                metadata = json.loads((directory / "inputs.json").read_text())
                source = "\n".join(path.read_text() for path in directory.glob("*.tf"))
                resources = re.findall(r'resource "([^"]+)" "([^"]+)"', source)
                self.assertEqual(set(metadata["ownedResourceTypes"]), {kind for kind, _ in resources})
                self.assertFalse(forbidden.intersection(metadata["ownedResourceTypes"]))
                self.assertFalse(any("iam" in kind for kind, _ in resources))
                for kind, label in resources:
                    self.assertTrue(any(address.split("[")[0] == f"{kind}.{label}" for address in metadata["ownedResourceAddresses"]))
                self.assertNotRegex(source, r'local-exec|remote-exec|provisioner|data "(?:external|http)"|yamldecode')
                self.assertNotIn("/Users/", (directory / "tests/roots.tftest.hcl").read_text())
                self.assertIn('version = "= 7.0.0"', (directory / "versions.tf").read_text())
                self.assertTrue(metadata["activationBlocked"])
        app = (MODULES / "gcp-appengine/main.tf").read_text()
        self.assertEqual(app.count("delete_service_on_destroy = true"), 2)
        self.assertEqual(app.count("noop_on_destroy           = false"), 2)
        self.assertEqual(app.count("create_before_destroy = false"), 2)
        remaining = json.loads((MODULES / "gcp-appengine/inputs.json").read_text())["remaining"]
        self.assertTrue(any("single-writer" in item for item in remaining))

    def test_source_operation_evidence_is_pinned_and_honest(self):
        evidence = json.loads(FIXTURE.read_text())
        self.assertEqual(evidence["providerVersion"], "7.0.0")
        self.assertIn("not cloud execution", evidence["proofLevel"])
        for name, source in evidence["sources"].items():
            self.assertIn("/v7.0.0/", source["url"])
            self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(source["operations"], name)
        traffic = evidence["sources"]["appengine_traffic"]["operations"]
        delete = next(operation for operation in traffic if operation["function"].endswith("Delete"))
        self.assertEqual(delete["methods"], [], "Traffic deletion is state-only, never a proved cloud cleanup")
        self.assertIn("exclusive nondefault", evidence["destroyCaveat"])

    def test_native_digest_paths_are_bound_to_exact_local_bytes(self):
        for name in ("gcp-appengine", "gcp-functions-gen2"):
            directory = MODULES / name
            tests = (directory / "tests/roots.tftest.hcl").read_text()
            digest = hashlib.sha256((directory / "tests/package.zip").read_bytes()).hexdigest()
            self.assertIn("sha256:" + digest, tests)
            source = (directory / "main.tf").read_text()
            self.assertIn('${local.digest}/main.zip', source)
            self.assertIn('filesha256(var.artifact.path) == local.digest', source)
            self.assertIn('source_md5hash', source)


if __name__ == "__main__":
    unittest.main()
