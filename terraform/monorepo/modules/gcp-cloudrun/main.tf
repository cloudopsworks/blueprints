##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Adapt the existing Cloud Run service primitive, not its project IAM/SA creators
# or tag-based image construction. Names are explicit existing target identities.
data "google_project" "external" { project_id = var.resource.project }
data "google_service_account" "external" {
  project    = var.resource.project
  account_id = split("@", var.configuration.serviceAccount)[0]
}
locals {
  revision = "${substr(var.resource.service, 0, 45)}-r-${substr(sha256(jsonencode({ artifact = var.artifact.digest, configuration = var.configuration, workload = var.workload })), 0, 12)}"
}
resource "google_cloud_run_v2_service" "component" {
  project             = data.google_project.external.project_id
  name                = var.resource.service
  location            = var.resource.region
  deletion_protection = false
  labels              = { "cloudopsworks-owner" = substr(var.owner_digest, 7, 40) }
  template {
    revision        = local.revision
    service_account = data.google_service_account.external.email
    containers {
      image = var.artifact.imageReference
      ports { container_port = var.workload.port }
      startup_probe {
        http_get {
          path = var.workload.healthPath
          port = var.workload.port
        }
      }
      liveness_probe {
        http_get {
          path = var.workload.healthPath
          port = var.workload.port
        }
      }
    }
  }
  traffic {
    type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
    revision = local.revision
    percent  = 100
  }
  lifecycle {
    precondition {
      condition     = var.artifact.format == "oci" && try(endswith(var.artifact.imageReference, "@${var.artifact.digest}"), false)
      error_message = "Cloud Run requires the exact verified OCI digest."
    }
    precondition {
      condition     = var.workload.kind == "http" && var.workload.port >= 1024 && var.workload.port <= 65535
      error_message = "Cloud Run requires the verified HTTP workload port."
    }
    precondition {
      condition     = data.google_service_account.external.email == var.configuration.serviceAccount
      error_message = "External service identity mismatch."
    }
  }
}
output "owned" { value = { service = google_cloud_run_v2_service.component.id } }
