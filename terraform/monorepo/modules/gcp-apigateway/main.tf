##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Fixed exact API/gateway identities; immutable API config content. No shared
# project, service account, domains, IAM bindings or registry resources are owned.
data "google_project" "external" {
  provider   = google-beta
  project_id = var.resource.project
}
resource "google_api_gateway_api" "component" {
  provider = google-beta
  project  = data.google_project.external.project_id
  api_id   = var.resource.api
  labels   = { "cloudopsworks-owner" = substr(var.owner_digest, 7, 40) }
}
resource "google_api_gateway_api_config" "component" {
  provider      = google-beta
  project       = data.google_project.external.project_id
  api           = google_api_gateway_api.component.api_id
  api_config_id = "v-${substr(sha256(jsonencode({ artifact = var.artifact.digest, backendServiceAccount = var.resource.backendServiceAccount })), 0, 40)}"
  openapi_documents {
    document {
      path     = var.artifact.format == "json" ? "openapi.json" : "openapi.yaml"
      contents = filebase64(var.artifact.path)
    }
  }
  gateway_config {
    backend_config { google_service_account = var.resource.backendServiceAccount }
  }
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = contains(["yaml", "json"], var.artifact.format) && var.workload.kind == "api" && try(filesha256(var.artifact.path) == local.digest, false)
      error_message = "API config requires verified immutable OpenAPI YAML/JSON bytes."
    }
  }
}
resource "google_api_gateway_gateway" "component" {
  provider   = google-beta
  project    = data.google_project.external.project_id
  gateway_id = var.resource.gateway
  region     = var.resource.region
  api_config = google_api_gateway_api_config.component.id
  labels     = { "cloudopsworks-owner" = substr(var.owner_digest, 7, 40) }
}
output "owned" { value = { api = google_api_gateway_api.component.id, config = google_api_gateway_api_config.component.id, gateway = google_api_gateway_gateway.component.id } }
