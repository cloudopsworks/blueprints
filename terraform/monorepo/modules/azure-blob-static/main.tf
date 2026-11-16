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
data "azurerm_resources" "external" {
  type                = "Microsoft.Storage/storageAccounts"
  name                = var.resource.account
  resource_group_name = var.resource.resourceGroup
}
resource "azurerm_storage_blob" "static" {
  for_each = { for file in var.artifact.files : file.key => file
  }
  name                   = "${trim(var.resource.prefix, "/")}/${each.key}"
  storage_account_name   = data.azurerm_resources.external.resources[0].name
  storage_container_name = var.resource.container
  type                   = "Block"
  source                 = each.value.path
  content_type           = each.value.contentType
  content_md5            = filemd5(each.value.path)
  lifecycle {
    precondition {
      condition     = contains(["zip", "tar.gz"], var.artifact.format) && var.workload.kind == "static" && var.resource.container == "$web" && length(data.azurerm_resources.external.resources) == 1 && lower(data.azurerm_resources.external.resources[0].id) == lower("/subscriptions/${var.resource.subscriptionId}/resourceGroups/${var.resource.resourceGroup}/providers/Microsoft.Storage/storageAccounts/${var.resource.account}") && length(var.artifact.files) > 0
      error_message = "A verified static object manifest in external $web is required."
    }
    precondition {
      condition     = can(regex("^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$", var.resource.prefix)) && !startswith(each.key, "/") && !contains(split("/", each.key), "..") && !contains(split("/", each.key), ".") && !strcontains(each.key, "\\")
      error_message = "Static keys cannot escape the frozen owned prefix."
    }

  }

}
output "owned_ids" {
  value = [for item in azurerm_storage_blob.static : item.id]
}
