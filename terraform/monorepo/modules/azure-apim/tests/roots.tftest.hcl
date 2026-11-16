mock_provider "azurerm" {
  mock_data "azurerm_resource_group" { defaults = { location = "eastus", id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external" } }
  mock_data "azurerm_service_plan" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", os_type = "Linux", sku_name = "EP1" } }
  mock_data "azurerm_storage_account" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", primary_blob_endpoint = "https://externalfixture.blob.core.windows.net/" } }
  mock_data "azurerm_user_assigned_identity" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", client_id = "00000000-0000-0000-0000-000000000002" } }
  mock_data "azurerm_container_app_environment" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external" } }
}
run "owned_mock_apply" {
  command = apply
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.apim", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "apiId" : "component", "serviceName" : "external", "apiPath" : "component" }
    configuration = { "kind" : "azure.apim" }
    workload      = { "kind" : "api" }
    artifact      = { "digest" : "sha256:15ab80b6ce752f8d391f6fd7648fe3a30d2fe0965b7d9e803388a7122d356a32", "format" : "json", "path" : "tests/openapi.json", "imageReference" : null, "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
run "api_exact_digest" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.apim", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "apiId" : "component", "serviceName" : "external", "apiPath" : "component" }
    configuration = { "kind" : "azure.apim" }
    workload      = { "kind" : "api" }
    artifact      = { "digest" : "sha256:15ab80b6ce752f8d391f6fd7648fe3a30d2fe0965b7d9e803388a7122d356a32", "format" : "json", "path" : "tests/openapi.json", "imageReference" : null, "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  assert {
    condition     = azurerm_api_management_api.component.name == "component"
    error_message = "Selected mode projection mismatch."
  }
}
run "reject_digest_mismatch" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.apim", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "apiId" : "component", "serviceName" : "external", "apiPath" : "component" }
    configuration = { "kind" : "azure.apim" }
    workload      = { "kind" : "api" }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "json", "path" : "tests/openapi.json", "imageReference" : null, "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  expect_failures = [azurerm_api_management_api.component]
}
