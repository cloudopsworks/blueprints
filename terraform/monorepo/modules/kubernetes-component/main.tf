##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Cluster and normal namespace are EXTERNAL. Only this component release and
# the fixed authoritative chart children belong to its independent native state.
data "kubernetes_namespace_v1" "external" {
  metadata { name = var.resource.namespace }
}
resource "helm_release" "component" {
  name              = var.release_name
  namespace         = data.kubernetes_namespace_v1.external.metadata[0].name
  chart             = var.chart_path
  description       = var.owner_digest
  create_namespace  = false
  atomic            = true
  cleanup_on_fail   = true
  wait              = true
  wait_for_jobs     = true
  timeout           = var.readiness_seconds
  skip_crds         = true
  disable_crd_hooks = true
  reuse_values      = false
  reset_values      = true
  values = [jsonencode({ monorepo = merge({
    enabled = true, preview = var.preview_options != null, image = var.artifact.imageReference,
    port    = var.workload.port, healthPath = var.workload.healthPath, replicas = 1
  }, var.preview_options == null ? {} : { host = var.preview_options.host, ingressClass = var.preview_options.ingressClass }) })]
  lifecycle {
    precondition {
      condition     = contains(["aws.eks", "gcp.gke", "azure.aks"], var.resource.kind) && var.resource.kind == var.configuration.kind
      error_message = "Only the exact resolved Kubernetes deployment family is accepted."
    }
    precondition {
      condition     = var.artifact.format == "oci" && endswith(var.artifact.imageReference, "@${var.artifact.digest}") && can(regex("^sha256:[0-9a-f]{64}$", var.artifact.digest))
      error_message = "Kubernetes workload requires the verified immutable image digest."
    }
    precondition {
      condition     = var.workload.kind == "http" && var.workload.port >= 1024 && var.workload.port <= 65535 && startswith(var.workload.healthPath, "/")
      error_message = "Kubernetes requires the validated HTTP workload contract."
    }
    precondition {
      condition     = can(regex("^[a-z][a-z0-9-]{0,47}$", var.release_name)) && can(regex("^sha256:[0-9a-f]{64}$", var.owner_digest))
      error_message = "Release and immutable owner are generated from the verified state handle."
    }
    precondition {
      condition     = fileexists("${var.chart_path}/Chart.yaml") && var.readiness_seconds >= 1 && var.readiness_seconds <= 3600
      error_message = "Fixed authoritative chart and bounded readiness are required."
    }
  }
}
output "owned" { value = { release = helm_release.component.name, namespace = helm_release.component.namespace, owner_digest = var.owner_digest } }
