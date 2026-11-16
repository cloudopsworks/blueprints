mock_provider "azurerm" {
  mock_data "azurerm_resource_group" { defaults = { location = "eastus", id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external" } }
  mock_data "azurerm_service_plan" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", os_type = "Linux", sku_name = "EP1" } }
  mock_data "azurerm_resources" {
    defaults = { resources = [{
      id                  = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture"
      name                = "externalfixture"
      resource_group_name = "external"
      location            = "eastus"
      type                = "Microsoft.Storage/storageAccounts"
      tags                = {}
    }] }
  }
}
run "owned_mock_apply" {
  command = apply
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.blob-static", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "account" : "externalfixture", "container" : "$web", "prefix" : "component" }
    configuration = { "kind" : "azure.blob-static" }
    workload      = { "kind" : "static" }
    artifact      = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [{ "path" : "tests/index.html", "key" : "index.html", "contentType" : "text/html" }] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  assert {
    condition     = azurerm_storage_blob.static["index.html"].name == "component/index.html"
    error_message = "Selected mode projection mismatch."
  }
}
run "prefix_bound" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.blob-static", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "account" : "externalfixture", "container" : "$web", "prefix" : "component" }
    configuration = { "kind" : "azure.blob-static" }
    workload      = { "kind" : "static" }
    artifact      = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [{ "path" : "tests/index.html", "key" : "index.html", "contentType" : "text/html" }] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  assert {
    condition     = azurerm_storage_blob.static["index.html"].name == "component/index.html"
    error_message = "Selected mode projection mismatch."
  }
}
run "reject_prefix_escape" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.blob-static", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "account" : "externalfixture", "container" : "$web", "prefix" : "component" }
    configuration = { "kind" : "azure.blob-static" }
    workload      = { "kind" : "static" }
    artifact      = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [{ "path" : "tests/index.html", "key" : "../escape", "contentType" : "text/html" }] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  expect_failures = [azurerm_storage_blob.static]
}
