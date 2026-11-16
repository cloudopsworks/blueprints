"""Pinned source/encoder proof; mocks are not live provider API proof."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FIXTURES = Path(__file__).parent / "fixtures/iac_capabilities"


class AzureSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((FIXTURES / "azure_source.json").read_text())
        cls.sources = {s["path"]: s for s in cls.fixture["sources"]}

    def source(self, path):
        return self.sources[path]["content"]

    def test_sources_are_exact_and_immutable_pinned(self):
        self.assertEqual(self.fixture["ref"], "v4.66.0")
        for source in self.sources.values():
            self.assertEqual(source["sha256"], hashlib.sha256(source["content"].encode()).hexdigest())
            self.assertIn("/" + self.fixture["commit"] + "/", source["url"])
            self.assertNotIn("/main/", source["url"])

    def test_flex_zip_field_is_rejected_operation_route(self):
        source = self.source("appservice_function_app_flex_consumption_resource.go")
        self.assertIn('helpers.GetCredentialsAndPublish(ctx, client, id, functionAppFlexConsumption.ZipDeployFile)', source)
        helper = self.source("appservice_helpers_publish_app.go")
        self.assertIn("GetSitePublishingCredentials(ctx, client, appID)", helper)
        self.assertIn("PublishZipDeployLocalFileKuduPush", helper)
        self.assertIn("req.SetBasicAuth(user, passwd)", helper)

    def test_standard_zip_update_is_path_triggered_not_hash_magic(self):
        for filename in ["appservice_linux_web_app_resource.go", "appservice_windows_web_app_resource.go",
                         "appservice_linux_web_app_slot_resource.go", "appservice_windows_web_app_slot_resource.go",
                         "appservice_linux_function_app_resource.go", "appservice_windows_function_app_resource.go"]:
            source = self.source(filename)
            self.assertIn('HasChange("zip_deploy_file")', source)
            self.assertIn("GetCredentialsAndPublish", source)
        for filename in ["appservice_linux_function_app_slot_resource.go", "appservice_windows_function_app_slot_resource.go"]:
            self.assertNotIn('"zip_deploy_file"', self.source(filename))

    def test_arm_extension_operation_and_isolated_delete(self):
        source = self.source("resource_resource_group_template_deployment_resource.go")
        self.assertIn('d.HasChange("parameters_content")', source)
        self.assertIn("client.CreateOrUpdate(ctx, id.ResourceGroup, id.DeploymentName, deployment)", source)
        self.assertIn("future.WaitForCompletionRef", source)
        guard = source.index("if deleteItemsInTemplate {")
        nested = source.index("deleteItemsProvisionedByTemplate", guard)
        otherwise = source.index("} else {", nested)
        delete = source.index("client.Delete(ctx, id.ResourceGroup, id.DeploymentName)", otherwise)
        self.assertLess(guard, nested)
        self.assertLess(nested, otherwise)
        self.assertLess(otherwise, delete)

    def test_exact_source_function_digest_encoder_and_decoder_roundtrip(self):
        if not shutil.which("go"):
            self.skipTest("Go required to execute extracted selected-provider encoder")
        source = self.source("appservice_helpers_fx_strings.go")
        def function(name):
            start = source.index("func " + name + "(")
            body = source.index("{", start)
            depth = 1
            end = body + 1
            while depth:
                depth += (source[end] == "{") - (source[end] == "}")
                end += 1
            return source[start:end]
        # Exact unmodified functions, with only their types/constants/pointer
        # dependency supplied by a stdlib-only harness. Not the whole provider.
        harness = '''package main
import("fmt";"strings";"encoding/json")
type FxStringPrefix string
const(FxStringPrefixDocker FxStringPrefix="DOCKER";FxStringPrefixNode FxStringPrefix="NODE";FxStringPrefixDotNetIsolated FxStringPrefix="DOTNET-ISOLATED";FxStringPrefixDotNet FxStringPrefix="DOTNET";FxStringPrefixPython FxStringPrefix="PYTHON";FxStringPrefixJava FxStringPrefix="JAVA";FxStringPrefixPowerShell FxStringPrefix="POWERSHELL")
var urlSchemes=[]string{"https://","http://"}
var pointer=struct{To func(string)*string}{func(v string)*string{return &v}}
type ApplicationStackDocker struct{ImageName,ImageTag,RegistryURL string}
type ApplicationStackLinuxFunctionApp struct{CustomHandler,DotNetIsolated bool;NodeVersion,DotNetVersion,PythonVersion,JavaVersion,PowerShellCoreVersion string;Docker []ApplicationStackDocker}
'''
        harness += function("EncodeFunctionAppLinuxFxVersion") + "\n" + function("DecodeFunctionAppDockerFxString")
        harness += '''
func main(){ cfg:=ApplicationStackDocker{ImageName:"component@sha256",ImageTag:strings.Repeat("a",64),RegistryURL:"https://fixture.azurecr.io"}; encoded:=*EncodeFunctionAppLinuxFxVersion([]ApplicationStackLinuxFunctionApp{{Docker:[]ApplicationStackDocker{cfg}}}); decoded,err:=DecodeFunctionAppDockerFxString(encoded,cfg); if err!=nil||len(decoded)!=1||decoded[0]!=cfg {panic("roundtrip")}; out,_:=json.Marshal(map[string]string{"encoded":encoded,"name":decoded[0].ImageName,"digest":decoded[0].ImageTag});fmt.Println(string(out))}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.go"
            path.write_text(harness)
            env = dict(os.environ, GOPROXY="off", GOSUMDB="off", GOWORK="off", GO111MODULE="off")
            result = subprocess.run(["go", "run", str(path)], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
        self.assertEqual(output["encoded"], "DOCKER|fixture.azurecr.io/component@sha256:" + "a" * 64)
        self.assertEqual(output["name"], "component@sha256")


if __name__ == "__main__":
    unittest.main()
