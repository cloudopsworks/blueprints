##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# The existing source bucket, runtime/build identities and trigger parents are
# external. The function, its revision and its immutable package object are owned.
data "google_project" "external" { project_id = var.resource.project }
data "google_storage_bucket" "external" { name = var.resource.iac.sourceBucket }
data "google_service_account" "external" {
  project    = var.resource.project
  account_id = split("@", var.configuration.serviceAccount)[0]
}
resource "google_storage_bucket_object" "package" {
  bucket         = data.google_storage_bucket.external.name
  name           = "cloudopsworks/${substr(var.owner_digest, 7, 64)}/${local.digest}/main.zip"
  source         = var.artifact.path
  content_type   = "application/zip"
  source_md5hash = filemd5(var.artifact.path)
  metadata       = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = var.artifact.format == "zip" && try(filesha256(var.artifact.path) == local.digest, false)
      error_message = "Native function package bytes disagree with their immutable digest."
    }
    precondition {
      condition     = var.configuration.iac.sourceBucket == var.resource.iac.sourceBucket && tostring(data.google_storage_bucket.external.project_number) == data.google_project.external.number
      error_message = "External package bucket identity mismatch."
    }
  }
}
resource "google_cloudfunctions2_function" "component" {
  project  = data.google_project.external.project_id
  name     = var.resource.functionName
  location = var.resource.region
  labels   = { "cloudopsworks-owner" = substr(var.owner_digest, 7, 40) }
  build_config {
    runtime         = var.configuration.runtime
    entry_point     = var.configuration.iac.entryPoint
    service_account = var.configuration.iac.buildServiceAccount
    source {
      storage_source {
        bucket     = google_storage_bucket_object.package.bucket
        object     = google_storage_bucket_object.package.name
        generation = google_storage_bucket_object.package.generation
      }
    }
  }
  service_config {
    service_account_email          = data.google_service_account.external.email
    all_traffic_on_latest_revision = true
  }
  dynamic "event_trigger" {
    for_each = var.resource.trigger.kind == "eventarc" ? [var.configuration.eventSource] : []
    content {
      event_type            = event_trigger.value.source == "pubsub" ? "google.cloud.pubsub.topic.v1.messagePublished" : "google.cloud.storage.object.v1.finalized"
      pubsub_topic          = event_trigger.value.source == "pubsub" ? event_trigger.value.resource : null
      service_account_email = data.google_service_account.external.email
      trigger_region        = var.resource.region
      dynamic "event_filters" {
        for_each = event_trigger.value.source == "storage-finalize" ? [event_trigger.value.resource] : []
        content {
          attribute = "bucket"
          value     = event_filters.value
        }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = var.workload.kind == "function" && !startswith(var.configuration.runtime, "rust")
      error_message = "A supported verified native Gen2 runtime is required."
    }
    precondition {
      condition     = data.google_service_account.external.email == var.configuration.serviceAccount
      error_message = "External runtime service account mismatch."
    }
    precondition {
      condition     = (var.resource.trigger.kind == "http" && var.configuration.eventSource == null) || (var.resource.trigger.kind == "eventarc" && try(contains(["pubsub", "storage-finalize"], var.configuration.eventSource.source) && var.configuration.eventSource.resource == var.resource.trigger.value, false))
      error_message = "Event type and source must match the trusted explicit probe and trigger."
    }
  }
}
output "owned" { value = { function = google_cloudfunctions2_function.component.id, package = google_storage_bucket_object.package.id } }
