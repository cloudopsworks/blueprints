##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

terraform {
  required_version = "= 1.11.4"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "= 4.66.0"
    }
  }

}
provider "azurerm" {
  subscription_id                 = var.resource.subscriptionId
  storage_use_azuread             = true
  resource_provider_registrations = "none"
  features {
    template_deployment {
      delete_nested_items_during_deletion = false
    }
  }

}
