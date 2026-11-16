##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

data "azurerm_windows_web_app" "parent_windows" {
  count               = !local.production && !local.linux ? 1 : 0
  name                = var.resource.appName
  resource_group_name = var.resource.resourceGroup
}
data "azurerm_linux_web_app" "parent_linux" {
  count               = !local.production && local.linux ? 1 : 0
  name                = var.resource.appName
  resource_group_name = var.resource.resourceGroup
}
data "azurerm_resource_group" "external" {
  name = var.resource.resourceGroup
}
locals {
  runtime_parts   = split("|", (var.configuration.runtime == null ? "" : var.configuration.runtime))
  runtime_name    = upper(try(local.runtime_parts[0], ""))
  runtime_version = try(local.runtime_parts[1], null)

  linux            = coalesce(var.resource.os, "linux") == "linux"
  production       = var.resource.slot == "production"
  zip              = var.resource.packageMode == "zip"
  flex             = false
  parent_id        = "/subscriptions/${var.resource.subscriptionId}/resourceGroups/${var.resource.resourceGroup}/providers/Microsoft.Web/sites/${var.resource.appName}"
  identity_id      = var.configuration.iac.identityId
  registry         = local.zip ? null : split("/", var.artifact.imageReference)[0]
  image            = local.zip ? null : join("/", slice(split("/", var.artifact.imageReference), 1, length(split("/", var.artifact.imageReference))))
  package_basename = local.flex ? "released-package.zip" : "main.zip"
  package_name     = local.zip ? "${trim(var.resource.iac.packageStorage.prefix, "/")}/${local.digest}/${local.package_basename}" : null
  package_account  = local.zip ? split("/", var.resource.iac.packageStorage.accountId)[8] : null
  package_uri      = local.zip ? "https://${local.package_account}.blob.core.windows.net/${var.resource.iac.packageStorage.container}/${local.package_name}?${trimprefix(var.package_read_sas, "?")}" : null
}
variable "package_read_sas" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Ephemeral TF_VAR only, validated read-only SAS from protected settings; never a lifecycle record."
}
data "azurerm_service_plan" "external" {
  name                = split("/", var.resource.iac.servicePlanId)[8]
  resource_group_name = split("/", var.resource.iac.servicePlanId)[4]
}
data "azurerm_user_assigned_identity" "external" {
  name                = split("/", local.identity_id)[8]
  resource_group_name = split("/", local.identity_id)[4]
}
data "azurerm_resources" "package" {
  type                = "Microsoft.Storage/storageAccounts"
  count               = local.zip ? 1 : 0
  name                = local.package_account
  resource_group_name = split("/", var.resource.iac.packageStorage.accountId)[4]
}
resource "azurerm_storage_blob" "package" {
  count                  = local.zip ? 1 : 0
  name                   = local.package_name
  storage_account_name   = data.azurerm_resources.package[0].resources[0].name
  storage_container_name = var.resource.iac.packageStorage.container
  type                   = "Block"
  source                 = var.artifact.path
  content_md5            = filemd5(var.artifact.path)
  lifecycle {
    precondition {
      condition     = length(data.azurerm_resources.package[0].resources) == 1 && filesha256(var.artifact.path) == local.digest && lower(data.azurerm_resources.package[0].resources[0].id) == lower(var.resource.iac.packageStorage.accountId)
      error_message = "Verified package digest mismatch."
    }
    precondition {
      condition     = can(regex("^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$", var.resource.iac.packageStorage.prefix))
      error_message = "Package cannot escape frozen owned prefix."
    }
  }
}
resource "azurerm_linux_web_app" "linux" {
  count               = local.linux && local.production && !local.flex ? 1 : 0
  name                = var.resource.appName
  resource_group_name = data.azurerm_resource_group.external.name
  location            = data.azurerm_resource_group.external.location
  service_plan_id     = data.azurerm_service_plan.external.id
  https_only          = true
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.external.id]
  }
  app_settings = local.zip ? {} : { WEBSITES_PORT = tostring(var.workload.port) }
  site_config {
    minimum_tls_version                           = "1.2"
    ftps_state                                    = "Disabled"
    health_check_path                             = var.workload.healthPath
    health_check_eviction_time_in_min             = 2
    container_registry_use_managed_identity       = !local.zip
    container_registry_managed_identity_client_id = local.zip ? null : data.azurerm_user_assigned_identity.external.client_id
    dynamic "application_stack" {
      for_each = local.zip ? [1] : []
      content {
        python_version      = local.runtime_name == "PYTHON" ? local.runtime_version : null
        node_version        = local.runtime_name == "NODE" ? local.runtime_version : null
        dotnet_version      = local.runtime_name == "DOTNETCORE" ? local.runtime_version : null
        ruby_version        = local.runtime_name == "RUBY" ? local.runtime_version : null
        java_version        = local.runtime_name == "JAVA" ? local.runtime_version : null
        java_server         = local.runtime_name == "JAVA" ? "JAVA" : null
        java_server_version = local.runtime_name == "JAVA" ? local.runtime_version : null
      }
    }
    dynamic "application_stack" {
      for_each = local.zip ? [] : [1]
      content {
        docker_image_name   = local.image
        docker_registry_url = "https://${local.registry}"
      }
    }
  }
  tags = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = local.zip ? (var.artifact.format == "zip" && local.runtime_version != null && contains(local.linux ? ["PYTHON", "NODE", "DOTNETCORE", "JAVA", "RUBY"] : ["NODE", "DOTNET", "JAVA"], local.runtime_name)) : (local.linux && var.artifact.format == "oci" && endswith(coalesce(var.artifact.imageReference, "invalid"), "@${var.artifact.digest}"))
      error_message = "Package mode/OS or immutable artifact mismatch."
    }
    precondition {
      condition     = lower(data.azurerm_service_plan.external.id) == lower(var.resource.iac.servicePlanId) && lower(data.azurerm_user_assigned_identity.external.id) == lower(local.identity_id) && lower(data.azurerm_service_plan.external.os_type) == lower(coalesce(var.resource.os, "linux")) && !contains(["FC1", "Y1"], upper(data.azurerm_service_plan.external.sku_name))
      error_message = "External plan or identity mismatch."
    }
  }
}
resource "azurerm_linux_web_app_slot" "linux_slot" {
  count          = local.linux && !local.production && !local.flex ? 1 : 0
  name           = var.resource.slot
  app_service_id = data.azurerm_linux_web_app.parent_linux[0].id
  https_only     = true
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.external.id]
  }
  app_settings = local.zip ? {} : { WEBSITES_PORT = tostring(var.workload.port) }
  site_config {
    minimum_tls_version                           = "1.2"
    ftps_state                                    = "Disabled"
    health_check_path                             = var.workload.healthPath
    health_check_eviction_time_in_min             = 2
    container_registry_use_managed_identity       = !local.zip
    container_registry_managed_identity_client_id = local.zip ? null : data.azurerm_user_assigned_identity.external.client_id
    dynamic "application_stack" {
      for_each = local.zip ? [1] : []
      content {
        python_version      = local.runtime_name == "PYTHON" ? local.runtime_version : null
        node_version        = local.runtime_name == "NODE" ? local.runtime_version : null
        dotnet_version      = local.runtime_name == "DOTNETCORE" ? local.runtime_version : null
        ruby_version        = local.runtime_name == "RUBY" ? local.runtime_version : null
        java_version        = local.runtime_name == "JAVA" ? local.runtime_version : null
        java_server         = local.runtime_name == "JAVA" ? "JAVA" : null
        java_server_version = local.runtime_name == "JAVA" ? local.runtime_version : null
      }
    }
    dynamic "application_stack" {
      for_each = local.zip ? [] : [1]
      content {
        docker_image_name   = local.image
        docker_registry_url = "https://${local.registry}"
      }
    }
  }
  tags = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = lower(data.azurerm_linux_web_app.parent_linux[0].id) == lower(local.parent_id) && lower(data.azurerm_linux_web_app.parent_linux[0].service_plan_id) == lower(var.resource.iac.servicePlanId)
      error_message = "External slot parent identity or plan mismatch."
    }
    precondition {
      condition     = local.zip ? (var.artifact.format == "zip" && local.runtime_version != null && contains(local.linux ? ["PYTHON", "NODE", "DOTNETCORE", "JAVA", "RUBY"] : ["NODE", "DOTNET", "JAVA"], local.runtime_name)) : (local.linux && var.artifact.format == "oci" && endswith(coalesce(var.artifact.imageReference, "invalid"), "@${var.artifact.digest}"))
      error_message = "Package mode/OS or immutable artifact mismatch."
    }
    precondition {
      condition     = lower(data.azurerm_service_plan.external.id) == lower(var.resource.iac.servicePlanId) && lower(data.azurerm_user_assigned_identity.external.id) == lower(local.identity_id) && lower(data.azurerm_service_plan.external.os_type) == lower(coalesce(var.resource.os, "linux")) && !contains(["FC1", "Y1"], upper(data.azurerm_service_plan.external.sku_name))
      error_message = "External plan or identity mismatch."
    }
  }
}
resource "azurerm_windows_web_app" "windows" {
  count               = !local.linux && local.production && !local.flex ? 1 : 0
  name                = var.resource.appName
  resource_group_name = data.azurerm_resource_group.external.name
  location            = data.azurerm_resource_group.external.location
  service_plan_id     = data.azurerm_service_plan.external.id
  https_only          = true
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.external.id]
  }
  app_settings = local.zip ? {} : { WEBSITES_PORT = tostring(var.workload.port) }
  site_config {
    application_stack {
      current_stack                = local.runtime_name == "DOTNET" ? "dotnet" : (local.runtime_name == "NODE" ? "node" : "java")
      dotnet_version               = local.runtime_name == "DOTNET" ? local.runtime_version : null
      node_version                 = local.runtime_name == "NODE" ? local.runtime_version : null
      java_version                 = local.runtime_name == "JAVA" ? local.runtime_version : null
      java_embedded_server_enabled = local.runtime_name == "JAVA" ? true : null
    }
    minimum_tls_version               = "1.2"
    ftps_state                        = "Disabled"
    health_check_path                 = var.workload.healthPath
    health_check_eviction_time_in_min = 2
  }
  tags = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = local.zip ? (var.artifact.format == "zip" && local.runtime_version != null && contains(local.linux ? ["PYTHON", "NODE", "DOTNETCORE", "JAVA", "RUBY"] : ["NODE", "DOTNET", "JAVA"], local.runtime_name)) : (local.linux && var.artifact.format == "oci" && endswith(coalesce(var.artifact.imageReference, "invalid"), "@${var.artifact.digest}"))
      error_message = "Package mode/OS or immutable artifact mismatch."
    }
    precondition {
      condition     = lower(data.azurerm_service_plan.external.id) == lower(var.resource.iac.servicePlanId) && lower(data.azurerm_user_assigned_identity.external.id) == lower(local.identity_id) && lower(data.azurerm_service_plan.external.os_type) == lower(coalesce(var.resource.os, "linux")) && !contains(["FC1", "Y1"], upper(data.azurerm_service_plan.external.sku_name))
      error_message = "External plan or identity mismatch."
    }
  }
}
resource "azurerm_windows_web_app_slot" "windows_slot" {
  count          = !local.linux && !local.production && !local.flex ? 1 : 0
  name           = var.resource.slot
  app_service_id = data.azurerm_windows_web_app.parent_windows[0].id
  https_only     = true
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.external.id]
  }
  app_settings = local.zip ? {} : { WEBSITES_PORT = tostring(var.workload.port) }
  site_config {
    application_stack {
      current_stack                = local.runtime_name == "DOTNET" ? "dotnet" : (local.runtime_name == "NODE" ? "node" : "java")
      dotnet_version               = local.runtime_name == "DOTNET" ? local.runtime_version : null
      node_version                 = local.runtime_name == "NODE" ? local.runtime_version : null
      java_version                 = local.runtime_name == "JAVA" ? local.runtime_version : null
      java_embedded_server_enabled = local.runtime_name == "JAVA" ? true : null
    }
    minimum_tls_version               = "1.2"
    ftps_state                        = "Disabled"
    health_check_path                 = var.workload.healthPath
    health_check_eviction_time_in_min = 2
  }
  tags = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = lower(data.azurerm_windows_web_app.parent_windows[0].id) == lower(local.parent_id) && lower(data.azurerm_windows_web_app.parent_windows[0].service_plan_id) == lower(var.resource.iac.servicePlanId)
      error_message = "External slot parent identity or plan mismatch."
    }
    precondition {
      condition     = local.zip ? (var.artifact.format == "zip" && local.runtime_version != null && contains(local.linux ? ["PYTHON", "NODE", "DOTNETCORE", "JAVA", "RUBY"] : ["NODE", "DOTNET", "JAVA"], local.runtime_name)) : (local.linux && var.artifact.format == "oci" && endswith(coalesce(var.artifact.imageReference, "invalid"), "@${var.artifact.digest}"))
      error_message = "Package mode/OS or immutable artifact mismatch."
    }
    precondition {
      condition     = lower(data.azurerm_service_plan.external.id) == lower(var.resource.iac.servicePlanId) && lower(data.azurerm_user_assigned_identity.external.id) == lower(local.identity_id) && lower(data.azurerm_service_plan.external.os_type) == lower(coalesce(var.resource.os, "linux")) && !contains(["FC1", "Y1"], upper(data.azurerm_service_plan.external.sku_name))
      error_message = "External plan or identity mismatch."
    }
  }
}
locals {
  extension_type = local.production ? "Microsoft.Web/sites/extensions" : "Microsoft.Web/sites/slots/extensions"
  extension_name = local.flex ? "[concat(parameters('appName'), '/onedeploy')]" : (local.production ? "[concat(parameters('appName'), '/ZipDeploy')]" : "[concat(parameters('appName'), '/', parameters('slot'), '/ZipDeploy')]")
  package_template = {
    "$schema"      = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    contentVersion = "1.0.0.0"
    parameters = {
      packageUri = { type = "securestring" }
      appName    = { type = "string" }
      slot       = { type = "string" }
    }
    resources = [{
      type       = local.extension_type
      apiVersion = local.flex ? "2022-09-01" : "2021-02-01"
      name       = local.extension_name
      location   = "[resourceGroup().location]"
      properties = local.flex ? {
        packageUri  = "[parameters('packageUri')]"
        remoteBuild = false
        } : {
        packageUri = "[parameters('packageUri')]"
        appOffline = true
      }
    }]
  }
}
resource "azurerm_resource_group_template_deployment" "package" {
  count               = local.zip ? 1 : 0
  name                = "cow-${substr(sha256(join("/", [local.parent_id, var.resource.slot])), 0, 16)}-${substr(local.digest, 0, 24)}"
  resource_group_name = data.azurerm_resource_group.external.name
  deployment_mode     = "Incremental"
  template_content    = jsonencode(local.package_template)
  parameters_content = jsonencode({
    packageUri = { value = local.package_uri }
    appName    = { value = var.resource.appName }
    slot       = { value = var.resource.slot }
  })
  depends_on = [azurerm_linux_web_app.linux, azurerm_linux_web_app_slot.linux_slot, azurerm_windows_web_app.windows, azurerm_windows_web_app_slot.windows_slot, azurerm_storage_blob.package]
  lifecycle {
    precondition {
      condition     = length(var.package_read_sas) > 0 && can(regex("(^|&)sp=r(&|$)", trimprefix(var.package_read_sas, "?"))) && can(regex("(^|&)spr=https(&|$)", trimprefix(var.package_read_sas, "?")))
      error_message = "Protected prevalidated package read-only SAS is required."
    }
  }
}
output "owned_ids" {
  value = concat([for item in azurerm_linux_web_app.linux : item.id], [for item in azurerm_linux_web_app_slot.linux_slot : item.id], [for item in azurerm_windows_web_app.windows : item.id], [for item in azurerm_windows_web_app_slot.windows_slot : item.id], [for item in azurerm_storage_blob.package : item.id], [for item in azurerm_resource_group_template_deployment.package : item.id])
}
