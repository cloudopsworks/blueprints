"""Preview environment native IaC proof; mocks/local API are not real CNI evidence."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "terraform/monorepo/modules/kubernetes-preview-environment"
PLUGINS = ROOT / "terraform/monorepo/capabilities/.terraform/providers"


class PreviewEnvironmentTests(unittest.TestCase):
    def command(self, cwd, *arguments):
        result = subprocess.run(["tofu", *arguments], cwd=cwd, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, f"{arguments}:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def prepare(self, directory):
        self.assertEqual(json.loads(self.command(ROOT, "version", "-json"))["terraform_version"], "1.11.4")
        self.assertTrue(PLUGINS.is_dir(), "Exact selected provider cache required")
        destination = Path(directory) / "root"
        shutil.copytree(MODULE, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
        self.command(destination, "init", "-backend=false", "-input=false", "-lockfile=readonly", f"-plugin-dir={PLUGINS.resolve()}")
        return destination

    def test_pinned_provider_native_schema_validation_and_mock_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="preview-env-native-") as temporary:
            root = self.prepare(temporary)
            self.command(root, "fmt", "-check", "-recursive")
            self.command(root, "validate", "-no-color")
            schemas = json.loads(self.command(root, "providers", "schema", "-json"))["provider_schemas"]
            self.assertEqual(set(schemas), {"registry.opentofu.org/hashicorp/kubernetes"})
            provider = schemas["registry.opentofu.org/hashicorp/kubernetes"]
            self.assertTrue(provider["resource_schemas"]["kubernetes_namespace_v1"]["block"]["block_types"]["metadata"]["block"]["attributes"]["uid"]["computed"])
            self.assertTrue(provider["data_source_schemas"]["kubernetes_resources"]["block"]["attributes"]["objects"]["computed"])
            output = self.command(root, "test", "-no-color")
            self.assertIn("14 passed, 0 failed", output)
            self.assertIn('run "owned_mock_apply"... pass', output)

    def test_actual_provider_offline_plan_owns_only_namespace_policies_and_probe_children(self):
        """Actual provider plan using a local read-only discovery/API fixture; no Apply."""
        requests = []
        class API(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                parsed = urlsplit(self.path)
                requests.append(self.path)
                if parsed.path == "/api":
                    result = {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]}
                elif parsed.path == "/apis":
                    result = {"kind": "APIGroupList", "apiVersion": "v1", "groups": [{"name": "apiextensions.k8s.io", "versions": [{"groupVersion": "apiextensions.k8s.io/v1", "version": "v1"}], "preferredVersion": {"groupVersion": "apiextensions.k8s.io/v1", "version": "v1"}}]}
                elif parsed.path == "/api/v1":
                    result = {"kind": "APIResourceList", "apiVersion": "v1", "groupVersion": "v1", "resources": [{"name": "namespaces", "singularName": "namespace", "namespaced": False, "kind": "Namespace", "verbs": ["get", "list"]}]}
                elif parsed.path == "/apis/apiextensions.k8s.io/v1":
                    result = {"kind": "APIResourceList", "apiVersion": "v1", "groupVersion": "apiextensions.k8s.io/v1", "resources": [{"name": "customresourcedefinitions", "singularName": "customresourcedefinition", "namespaced": False, "kind": "CustomResourceDefinition", "verbs": ["get", "list"]}]}
                elif parsed.path == "/apis/apiextensions.k8s.io/v1/customresourcedefinitions":
                    result = {"kind": "CustomResourceDefinitionList", "apiVersion": "apiextensions.k8s.io/v1", "items": []}
                elif parsed.path == "/openapi/v2":
                    result = {"swagger": "2.0", "info": {"title": "offline", "version": "v1"}, "paths": {}, "definitions": {
                        "io.k8s.api.core.v1.Namespace": {"type": "object", "x-kubernetes-group-version-kind": [{"group": "", "version": "v1", "kind": "Namespace"}], "properties": {"apiVersion": {"type": "string"}, "kind": {"type": "string"}, "metadata": {"$ref": "#/definitions/io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta"}}},
                        "io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta": {"type": "object", "properties": {"name": {"type": "string"}, "uid": {"type": "string"}, "labels": {"type": "object", "additionalProperties": {"type": "string"}}}}
                    }}
                elif parsed.path == "/api/v1/namespaces":
                    selector = parse_qs(parsed.query).get("fieldSelector", [""])[0]
                    name = selector.removeprefix("metadata.name=")
                    if name not in ("control", "ingress"):
                        self.send_error(400)
                        return
                    result = {"kind": "NamespaceList", "apiVersion": "v1", "metadata": {"resourceVersion": "1"}, "items": [{"kind": "Namespace", "apiVersion": "v1", "metadata": {"name": name, "uid": name + "-external-uid", "labels": {"role": name}}}]}
                else:
                    self.send_error(404)
                    return
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                self.send_error(405)
            do_PUT = do_POST
            do_PATCH = do_POST
            do_DELETE = do_POST
        server = ThreadingHTTPServer(("127.0.0.1", 0), API)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="preview-env-offline-") as temporary:
                root = self.prepare(temporary)
                kubeconfig = root / "fixture-kubeconfig.json"
                kubeconfig.write_text(json.dumps({"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "offline", "cluster": {"server": f"http://127.0.0.1:{server.server_port}"}}], "contexts": [{"name": "offline", "context": {"cluster": "offline", "user": "offline"}}], "current-context": "offline", "users": [{"name": "offline", "user": {}}]}))
                inputs = json.loads((root / "tests/modes.tftest.json").read_text())["variables"]
                inputs["kubeconfig_path"] = str(kubeconfig)
                (root / "operation.tfvars.json").write_text(json.dumps(inputs))
                self.command(root, "plan", "-refresh=false", "-input=false", "-no-color", "-var-file=operation.tfvars.json", "-out=reviewed.plan")
                plan = json.loads(self.command(root, "show", "-json", "reviewed.plan"))
                changes = {item["address"]: item for item in plan["resource_changes"] if item["mode"] == "managed"}
                self.assertEqual(len(changes), 8)
                self.assertEqual(sum(item["type"] == "kubernetes_namespace_v1" for item in changes.values()), 1)
                self.assertTrue(all(item["change"]["actions"] == ["create"] for item in changes.values()))
                pods = [item["change"]["after"] for item in changes.values() if item["type"] == "kubernetes_pod_v1"]
                self.assertEqual({pod["metadata"][0]["namespace"] for pod in pods if pod["metadata"][0]["namespace"] in ("control", "ingress")}, {"control", "ingress"})
                self.assertTrue(any("fieldSelector=metadata.name%3Dcontrol" in path for path in requests))
                self.assertTrue(any("fieldSelector=metadata.name%3Dingress" in path for path in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_fixed_authority_inputs_and_honest_delete_boundary(self):
        metadata = json.loads((MODULE / "inputs.json").read_text())
        self.assertTrue(metadata["activationBlocked"])
        self.assertIn("no atomic UID-conditional", metadata["deleteSemantics"])
        self.assertEqual(metadata["externalParents"][:3], ["Kubernetes cluster", "existing control namespace", "existing ingress namespace"])
        text = "\n".join(path.read_text() for path in MODULE.glob("*.tf"))
        self.assertNotRegex(text, r'\b(provisioner|local-exec|import)\s*["{]')
        self.assertNotIn("exec {", text)
        self.assertNotIn("helm_release", text)
        self.assertEqual(re.findall(r'resource "kubernetes_namespace_v1" "([^"]+)"', text), ["environment"])
        self.assertEqual((MODULE / "terragrunt.hcl").read_text().splitlines()[-1], "terraform {}")
        fixture = json.loads((ROOT / "tests/monorepo/fixtures/iac_capabilities/kubernetes_delete_source.json").read_text())
        namespace = next(source for source in fixture["sources"] if source["name"] == "namespace")
        self.assertEqual(hashlib.sha256(namespace["content"].encode()).hexdigest(), namespace["sha256"])
        self.assertIn("metav1.DeleteOptions{}", namespace["content"])
        self.assertIn("/v2.38.0/", namespace["url"])


if __name__ == "__main__":
    unittest.main()
