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
    resource      = { "provider" : "azure", "kind" : "azure.containerapps", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "containerName" : "api", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external" } }
    configuration = { "kind" : "azure.containerapps", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "cpu" : 0.5, "memory" : "1Gi" } }
    workload      = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
run "digest_revision" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.containerapps", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "containerName" : "api", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external" } }
    configuration = { "kind" : "azure.containerapps", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "cpu" : 0.5, "memory" : "1Gi" } }
    workload      = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  assert {
    condition     = azurerm_container_app.component.template[0].container[0].image == "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    error_message = "Selected mode projection mismatch."
  }
}
run "reject_mutable_tag" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.containerapps", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "containerName" : "api", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external" } }
    configuration = { "kind" : "azure.containerapps", "iac" : { "managedEnvironmentId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "cpu" : 0.5, "memory" : "1Gi" } }
    workload      = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component:latest", "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  expect_failures = [azurerm_container_app.component]
}
