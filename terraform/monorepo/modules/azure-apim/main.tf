##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

data "azurerm_resource_group" "external" {
  name = var.resource.resourceGroup
}
data "azurerm_api_management" "external" {
  name                = var.resource.serviceName
  resource_group_name = var.resource.resourceGroup
}
resource "azurerm_api_management_api" "component" {
  name                  = var.resource.apiId
  resource_group_name   = data.azurerm_resource_group.external.name
  api_management_name   = data.azurerm_api_management.external.name
  revision              = "1"
  display_name          = var.resource.apiId
  path                  = var.resource.apiPath
  protocols             = ["https"]
  subscription_required = false
  import {
    content_format = var.artifact.format == "json" ? "openapi+json" : "openapi"
    content_value  = file(var.artifact.path)
  }
  lifecycle {
    precondition {
      condition     = contains(["json", "yaml"], var.artifact.format) && var.workload.kind == "api" && filesha256(var.artifact.path) == local.digest
      error_message = "A verified immutable OpenAPI document is required."
    }

  }

}
output "owned_ids" {
  value = [azurerm_api_management_api.component.id]
}
