##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Reuse the App Engine version primitive under the reviewed exclusive NONDEFAULT
# service contract. Version Delete removes the WHOLE owned service and versions.
# Same-mode replacements intentionally delete before create (downtime). Historical
# ownership, single-writer scope, inventory and saved-plan gates belong to the
# trusted executor; these flags alone never authorize takeover of an old service.
# External application/project/bucket/IAM/SA resources are never managed here.
# No source YAML is evaluated: sole Go binds the closed projection to its bytes.
data "google_project" "external" { project_id = var.resource.project }
data "google_service_account" "external" {
  project    = var.resource.project
  account_id = split("@", var.configuration.iac.serviceAccount)[0]
}
locals {
  app                 = var.configuration.appConfig
  standard            = local.app.environment == "standard"
  native              = var.artifact.format == "zip"
  version_hash        = sha256(jsonencode({ artifact = var.artifact.digest, config = var.configuration, workload = var.workload }))
  version_hash_length = local.standard ? 40 : max(16, min(40, 51 - length(var.resource.service) - length(var.resource.project)))
  version             = "v-${substr(local.version_hash, 0, local.version_hash_length)}"
  scaling             = local.app.scaling
}
data "google_storage_bucket" "external" {
  count = local.native ? 1 : 0
  name  = var.resource.iac.sourceBucket
}
resource "google_storage_bucket_object" "package" {
  count          = local.native ? 1 : 0
  bucket         = data.google_storage_bucket.external[0].name
  name           = "cloudopsworks/${substr(var.owner_digest, 7, 64)}/${local.digest}/main.zip"
  source         = var.artifact.path
  content_type   = "application/zip"
  source_md5hash = filemd5(var.artifact.path)
  metadata       = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = try(filesha256(var.artifact.path) == local.digest, false)
      error_message = "App Engine package bytes disagree with their immutable digest."
    }
    precondition {
      condition     = var.configuration.iac.sourceBucket == var.resource.iac.sourceBucket && tostring(data.google_storage_bucket.external[0].project_number) == data.google_project.external.number
      error_message = "External source bucket identity mismatch."
    }
  }
}
resource "google_app_engine_standard_app_version" "component" {
  count                     = local.standard ? 1 : 0
  project                   = data.google_project.external.project_id
  service                   = var.resource.service
  version_id                = local.version
  runtime                   = local.app.runtime
  instance_class            = local.app.instanceClass
  service_account           = data.google_service_account.external.email
  delete_service_on_destroy = true
  noop_on_destroy           = false
  dynamic "entrypoint" {
    for_each = local.app.entrypoint == null ? [] : [local.app.entrypoint]
    content { shell = entrypoint.value }
  }
  deployment {
    zip { source_url = "https://storage.googleapis.com/${google_storage_bucket_object.package[0].bucket}/${google_storage_bucket_object.package[0].name}" }
  }
  dynamic "manual_scaling" {
    for_each = try(local.scaling.kind == "manual", false) ? [local.scaling] : []
    content { instances = manual_scaling.value.instances }
  }
  dynamic "basic_scaling" {
    for_each = try(local.scaling.kind == "basic", false) ? [local.scaling] : []
    content {
      max_instances = basic_scaling.value.maxInstances
      idle_timeout  = basic_scaling.value.idleTimeout
    }
  }
  dynamic "automatic_scaling" {
    for_each = try(local.scaling.kind == "automatic", false) ? [local.scaling] : []
    content {
      max_concurrent_requests = automatic_scaling.value.maxConcurrentRequests
      min_idle_instances      = automatic_scaling.value.minIdleInstances
      max_idle_instances      = automatic_scaling.value.maxIdleInstances
      min_pending_latency     = automatic_scaling.value.minPendingLatency
      max_pending_latency     = automatic_scaling.value.maxPendingLatency
      standard_scheduler_settings {
        min_instances                 = automatic_scaling.value.minInstances
        max_instances                 = automatic_scaling.value.maxInstances
        target_cpu_utilization        = automatic_scaling.value.targetCpuUtilization
        target_throughput_utilization = automatic_scaling.value.targetThroughputUtilization
      }
    }
  }
  lifecycle {
    create_before_destroy = false
    precondition {
      condition     = local.native && var.workload.kind == "http" && data.google_service_account.external.email == var.configuration.iac.serviceAccount && local.app.service == var.resource.service && can(regex("^sha256:[0-9a-f]{64}$", local.app.sourceDigest))
      error_message = "Standard version requires the source-bound native App Engine config."
    }
  }
}
resource "google_app_engine_flexible_app_version" "component" {
  count                     = local.standard ? 0 : 1
  project                   = data.google_project.external.project_id
  service                   = var.resource.service
  version_id                = local.version
  runtime                   = local.app.runtime
  service_account           = data.google_service_account.external.email
  delete_service_on_destroy = true
  noop_on_destroy           = false
  dynamic "entrypoint" {
    for_each = local.app.entrypoint == null ? [] : [local.app.entrypoint]
    content { shell = entrypoint.value }
  }
  dynamic "flexible_runtime_settings" {
    for_each = local.app.runtimeConfig == null ? [] : [local.app.runtimeConfig]
    content {
      operating_system = flexible_runtime_settings.value.operatingSystem
      runtime_version  = flexible_runtime_settings.value.runtimeVersion
    }
  }
  deployment {
    dynamic "zip" {
      for_each = local.native ? [1] : []
      content { source_url = "https://storage.googleapis.com/${google_storage_bucket_object.package[0].bucket}/${google_storage_bucket_object.package[0].name}" }
    }
    dynamic "container" {
      for_each = local.native ? [] : [1]
      content { image = var.artifact.imageReference }
    }
  }
  liveness_check { path = var.workload.healthPath }
  readiness_check { path = var.workload.healthPath }
  dynamic "manual_scaling" {
    for_each = try(local.scaling.kind == "manual", false) ? [local.scaling] : []
    content { instances = manual_scaling.value.instances }
  }
  dynamic "automatic_scaling" {
    for_each = try(local.scaling.kind == "automatic", false) ? [local.scaling] : []
    content {
      min_total_instances     = automatic_scaling.value.minInstances
      max_total_instances     = automatic_scaling.value.maxInstances
      max_concurrent_requests = automatic_scaling.value.maxConcurrentRequests
      min_idle_instances      = automatic_scaling.value.minIdleInstances
      max_idle_instances      = automatic_scaling.value.maxIdleInstances
      min_pending_latency     = automatic_scaling.value.minPendingLatency
      max_pending_latency     = automatic_scaling.value.maxPendingLatency
      cpu_utilization { target_utilization = automatic_scaling.value.targetCpuUtilization }
    }
  }
  lifecycle {
    precondition {
      condition     = 51 - length(var.resource.service) - length(var.resource.project) >= 16
      error_message = "Flexible service/project identity leaves insufficient space for an immutable version ID."
    }

    create_before_destroy = false
    precondition {
      condition     = local.app.environment == "flexible" && data.google_service_account.external.email == var.configuration.iac.serviceAccount && local.app.service == var.resource.service && can(regex("^sha256:[0-9a-f]{64}$", local.app.sourceDigest)) && var.workload.kind == "http" && var.workload.port == 8080
      error_message = "Flexible App Engine requires source-bound config and HTTP port 8080."
    }
    precondition {
      condition     = local.native ? local.app.runtimeConfig != null : (var.artifact.format == "oci" && local.app.runtime == "custom" && try(endswith(var.artifact.imageReference, "@${var.artifact.digest}") && strcontains(var.artifact.imageReference, ".pkg.dev/"), false))
      error_message = "Flexible native requires explicit runtime settings; custom OCI requires an exact Artifact Registry digest."
    }
    precondition {
      condition     = local.scaling == null || try(local.scaling.kind != "basic" && (local.scaling.kind != "automatic" || local.scaling.targetCpuUtilization != null) && local.scaling.targetThroughputUtilization == null, false)
      error_message = "Flexible scaling cannot silently drop unsupported fields or its required CPU target."
    }
  }
}
resource "google_app_engine_service_split_traffic" "component" {
  project         = data.google_project.external.project_id
  service         = var.resource.service
  migrate_traffic = false
  split {
    shard_by    = "IP"
    allocations = { (local.version) = 1 }
  }
  depends_on = [google_app_engine_standard_app_version.component, google_app_engine_flexible_app_version.component]
}
output "owned" {
  value = {
    version  = local.standard ? google_app_engine_standard_app_version.component[0].id : google_app_engine_flexible_app_version.component[0].id
    traffic  = google_app_engine_service_split_traffic.component.id
    packages = [for object in google_storage_bucket_object.package : object.id]
  }
}
