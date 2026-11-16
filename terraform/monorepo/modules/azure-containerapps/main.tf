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
data "azurerm_container_app_environment" "external" {
  name                = split("/", var.configuration.iac.managedEnvironmentId)[8]
  resource_group_name = split("/", var.configuration.iac.managedEnvironmentId)[4]

}
data "azurerm_user_assigned_identity" "external" {
  name                = split("/", var.configuration.iac.identityId)[8]
  resource_group_name = split("/", var.configuration.iac.identityId)[4]

}
resource "azurerm_container_app" "component" {
  name                         = var.resource.appName
  resource_group_name          = data.azurerm_resource_group.external.name
  container_app_environment_id = data.azurerm_container_app_environment.external.id
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.external.id]
  }
  registry {
    server   = split("/", var.artifact.imageReference)[0]
    identity = data.azurerm_user_assigned_identity.external.id
  }
  template {
    revision_suffix = "v-${substr(local.digest, 0, 20)}"
    container {
      name   = var.resource.containerName
      image  = var.artifact.imageReference
      cpu    = coalesce(var.configuration.iac.cpu, 0.5)
      memory = coalesce(var.configuration.iac.memory, "1Gi")
      liveness_probe {
        transport = "HTTP"
        port      = var.workload.port
        path      = var.workload.healthPath
      }
      readiness_probe {
        transport = "HTTP"
        port      = var.workload.port
        path      = var.workload.healthPath
      }

    }

  }
  ingress {
    external_enabled = true
    target_port      = var.workload.port
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
  tags = { "cloudopsworks-owner" = var.owner_digest
  }
  lifecycle {
    precondition {
      condition     = var.artifact.format == "oci" && endswith(coalesce(var.artifact.imageReference, "invalid"), "@${var.artifact.digest}")
      error_message = "A verified OCI digest reference is required."
    }
    precondition {
      condition     = lower(data.azurerm_container_app_environment.external.id) == lower(var.resource.iac.managedEnvironmentId) && lower(data.azurerm_user_assigned_identity.external.id) == lower(var.configuration.iac.identityId)
      error_message = "External managed environment identity mismatch."
    }

  }

}
output "owned_ids" {
  value = [azurerm_container_app.component.id]
}
