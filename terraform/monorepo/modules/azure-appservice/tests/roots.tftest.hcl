mock_provider "azurerm" {
  mock_data "azurerm_windows_function_app" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/sites/component", service_plan_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
  mock_data "azurerm_linux_function_app" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/sites/component", service_plan_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
  mock_data "azurerm_windows_web_app" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/sites/component", service_plan_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
  mock_data "azurerm_linux_web_app" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/sites/component", service_plan_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
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
  mock_data "azurerm_user_assigned_identity" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", client_id = "00000000-0000-0000-0000-000000000002" } }

}
run "owned_mock_apply" {
  command = apply
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = length(azurerm_linux_web_app.linux) == 1
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name == "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.package[0].template_content).parameters.packageUri.type == "securestring"
    error_message = "Selected mode projection mismatch."
  }
}
run "linux_production_zip" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = length(azurerm_linux_web_app.linux) == 1
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name == "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.package[0].template_content).parameters.packageUri.type == "securestring"
    error_message = "Selected mode projection mismatch."
  }
}
run "linux_production_container" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "container", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = length(azurerm_linux_web_app.linux) == 1
    error_message = "Selected mode projection mismatch."
  }
}
run "linux_staging_zip" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "staging", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = length(azurerm_linux_web_app_slot.linux_slot) == 1
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name == "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.package[0].template_content).parameters.packageUri.type == "securestring"
    error_message = "Selected mode projection mismatch."
  }
}
run "linux_staging_container" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "staging", "packageMode" : "container", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = length(azurerm_linux_web_app_slot.linux_slot) == 1
    error_message = "Selected mode projection mismatch."
  }
}
run "windows_production_zip" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "windows", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "NODE|~20", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  override_data {
    target = data.azurerm_service_plan.external
    values = { os_type = "Windows", id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" }
  }
  assert {
    condition     = length(azurerm_windows_web_app.windows) == 1
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name == "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.package[0].template_content).parameters.packageUri.type == "securestring"
    error_message = "Selected mode projection mismatch."
  }
}
run "windows_staging_zip" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "windows", "architecture" : "x86_64", "appName" : "component", "slot" : "staging", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "NODE|~20", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  override_data {
    target = data.azurerm_service_plan.external
    values = { os_type = "Windows", id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" }
  }
  assert {
    condition     = length(azurerm_windows_web_app_slot.windows_slot) == 1
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name == "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.package[0].template_content).parameters.packageUri.type == "securestring"
    error_message = "Selected mode projection mismatch."
  }
}
run "changed_digest_changes_owned_object" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:730191a756b76e72981480fdb102bb4292c19e7831acdd474b5b32a74d7d3dd6", "format" : "zip", "path" : "tests/changed-package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = azurerm_storage_blob.package[0].name != "component/b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351/main.zip"
    error_message = "Selected mode projection mismatch."
  }
}
run "reject_digest_mismatch" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  expect_failures = [azurerm_storage_blob.package]
}
run "reject_broad_package_sas" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=rw&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  expect_failures = [azurerm_resource_group_template_deployment.package]
}
run "reject_unknown_runtime" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "INVALID|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  expect_failures = [azurerm_linux_web_app.linux]
}
run "sensitive_package_parameter" {
  command = plan
  variables {
    resource         = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "zip", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    configuration    = { "kind" : "azure.appservice", "runtime" : "PYTHON|3.12", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external", "packageStorage" : { "accountId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Storage/storageAccounts/externalfixture", "container" : "packages", "prefix" : "component" } } }
    workload         = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact         = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : "tests/package.zip", "imageReference" : null, "files" : [] }
    owner_digest     = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    package_read_sas = "sv=2025-01-05&spr=https&sp=r&sr=c&se=2099-01-01T00%3A00%3A00Z&sig=fixture"
  }
  assert {
    condition     = issensitive(azurerm_resource_group_template_deployment.package[0].parameters_content)
    error_message = "Expected bounded projection."
  }
}
run "container_without_native_configuration" {
  command = plan
  variables {
    resource      = { "provider" : "azure", "kind" : "azure.appservice", "subscriptionId" : "00000000-0000-0000-0000-000000000001", "resourceGroup" : "external", "ownership" : "managed", "os" : "linux", "architecture" : "x86_64", "appName" : "component", "slot" : "production", "packageMode" : "container", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
    configuration = { "kind" : "azure.appservice", "iac" : { "servicePlanId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external", "identityId" : "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external" } }
    workload      = { "kind" : "http", "port" : 3000, "healthPath" : "/ready" }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "fixture.azurecr.io/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
    owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
