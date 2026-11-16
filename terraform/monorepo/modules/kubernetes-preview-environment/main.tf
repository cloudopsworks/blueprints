# Copyright 2026 Cloud Ops Works LLC. Apache-2.0.
# Sole environment-state owner. The runtime binds historical namespace UID and
# checks fresh PR/UID/ownership immediately before each saved apply under the
# common single-writer group. Provider DeleteOptions are NOT UID-conditional.
locals {
  labels = {
    "cloudopsworks.io/managed-by"    = "blueprints-monorepo"
    "cloudopsworks.io/repository-id" = var.repository_id
    "cloudopsworks.io/pr"            = tostring(var.pr_number)
    "cloudopsworks.io/target-id"     = var.target_id
  }
  annotations = { "cloudopsworks.io/owner-digest" = var.owner_digest }
  probe_key   = substr(sha256("${var.repository_id}:${var.pr_number}:${var.target_id}"), 0, 20)
  # Only these repository-owned constant bytes execute, not YAML/source commands.
  server = "import http.server; http.server.HTTPServer(('0.0.0.0',8000),http.server.BaseHTTPRequestHandler).serve_forever()"
}
resource "kubernetes_namespace_v1" "environment" {
  metadata {
    name = var.namespace
    labels = merge(local.labels, {
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "v1.31"
      "pod-security.kubernetes.io/audit"           = "restricted"
      "pod-security.kubernetes.io/audit-version"   = "v1.31"
      "pod-security.kubernetes.io/warn"            = "restricted"
      "pod-security.kubernetes.io/warn-version"    = "v1.31"
    })
    annotations = local.annotations
  }
  lifecycle {
    precondition {
      condition     = contains(["aws.eks", "gcp.gke", "azure.aks"], var.resource.kind) && var.configuration.kind == var.resource.kind && var.resource.namespace == var.namespace
      error_message = "Environment requires the exact validated Kubernetes StateHandle namespace/family."
    }
  }
}
# Shared control/ingress namespaces are read-only external parents, never adopted.
data "kubernetes_resources" "control" {
  api_version    = "v1"
  kind           = "Namespace"
  field_selector = "metadata.name=${var.isolation.controlNamespace}"
  limit          = 2
  lifecycle {
    postcondition {
      condition     = try(length(self.objects) == 1 && self.objects[0].metadata.name == var.isolation.controlNamespace, false)
      error_message = "External control namespace read must resolve exactly the protected parent."
    }
  }
}
data "kubernetes_resources" "ingress" {
  api_version    = "v1"
  kind           = "Namespace"
  field_selector = "metadata.name=${var.isolation.ingressNamespace}"
  limit          = 2
  lifecycle {
    postcondition {
      condition     = try(length(self.objects) == 1 && self.objects[0].metadata.name == var.isolation.ingressNamespace && alltrue([for key, value in var.isolation.ingressNamespaceSelector : lookup(self.objects[0].metadata.labels, key, "") == value]), false)
      error_message = "Resolved external ingress namespace must exist uniquely and still match its protected selector."
    }
  }
}
resource "kubernetes_network_policy_v1" "default_deny" {
  metadata {
    name        = "cloudopsworks-default-deny"
    namespace   = kubernetes_namespace_v1.environment.metadata[0].name
    labels      = local.labels
    annotations = local.annotations
  }
  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }
}
resource "kubernetes_network_policy_v1" "same_namespace" {
  metadata {
    name        = "cloudopsworks-same-namespace"
    namespace   = kubernetes_namespace_v1.environment.metadata[0].name
    labels      = local.labels
    annotations = local.annotations
  }
  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
    ingress {
      from {
        pod_selector {}
      }
    }
    egress {
      to {
        pod_selector {}
      }
    }
  }
}
resource "kubernetes_network_policy_v1" "dns" {
  metadata {
    name        = "cloudopsworks-dns"
    namespace   = kubernetes_namespace_v1.environment.metadata[0].name
    labels      = local.labels
    annotations = local.annotations
  }
  spec {
    pod_selector {}
    policy_types = ["Egress"]
    egress {
      to {
        namespace_selector { match_labels = var.isolation.dnsNamespaceSelector }
        pod_selector { match_labels = var.isolation.dnsPodSelector }
      }
      ports {
        port     = "53"
        protocol = "UDP"
      }
      ports {
        port     = "53"
        protocol = "TCP"
      }
    }
  }
}
resource "kubernetes_network_policy_v1" "ingress" {
  metadata {
    name        = "cloudopsworks-ingress"
    namespace   = kubernetes_namespace_v1.environment.metadata[0].name
    labels      = local.labels
    annotations = local.annotations
  }
  spec {
    pod_selector {}
    policy_types = ["Ingress"]
    ingress {
      from {
        namespace_selector { match_labels = var.isolation.ingressNamespaceSelector }
        pod_selector { match_labels = var.isolation.ingressPodSelector }
      }
    }
  }
}
locals {
  probes = {
    canary  = { name = "cloudopsworks-canary", namespace = kubernetes_namespace_v1.environment.metadata[0].name, labels = {} }
    control = { name = "cw-control-${local.probe_key}", namespace = data.kubernetes_resources.control.objects[0].metadata.name, labels = {} }
    ingress = { name = "cw-ingress-${local.probe_key}", namespace = data.kubernetes_resources.ingress.objects[0].metadata.name, labels = var.isolation.ingressPodSelector }
  }
}
resource "kubernetes_pod_v1" "probe" {
  for_each = local.probes
  metadata {
    name      = each.value.name
    namespace = each.value.namespace
    labels    = merge(each.value.labels, local.labels, { "cloudopsworks.io/probe" = each.key })
    annotations = merge(local.annotations, {
      "cloudopsworks.io/environment-uid" = kubernetes_namespace_v1.environment.metadata[0].uid
    })
  }
  spec {
    restart_policy                  = "Never"
    host_network                    = false
    host_pid                        = false
    host_ipc                        = false
    automount_service_account_token = false
    security_context {
      run_as_non_root = true
      run_as_user     = "65532"
      seccomp_profile { type = "RuntimeDefault" }
    }
    container {
      name    = "probe"
      image   = var.isolation.probeImage
      command = ["python3", "-c", local.server]
      security_context {
        privileged                 = false
        allow_privilege_escalation = false
        read_only_root_filesystem  = true
        capabilities { drop = ["ALL"] }
      }
      resources {
        requests = { cpu = "10m", memory = "32Mi" }
        limits   = { cpu = "100m", memory = "64Mi" }
      }
      readiness_probe {
        tcp_socket { port = "8000" }
      }
    }
  }
  depends_on = [
    kubernetes_network_policy_v1.default_deny, kubernetes_network_policy_v1.same_namespace,
    kubernetes_network_policy_v1.dns, kubernetes_network_policy_v1.ingress
  ]
  lifecycle {
    precondition {
      condition     = var.isolation.controlNamespace != var.namespace && var.isolation.ingressNamespace != var.namespace && var.isolation.controlNamespace != var.isolation.ingressNamespace
      error_message = "Probe parent namespaces must be distinct existing namespaces outside the preview."
    }
    precondition {
      condition     = anytrue([for key, value in var.isolation.ingressNamespaceSelector : lookup(data.kubernetes_resources.control.objects[0].metadata.labels, key, "") != value])
      error_message = "Control namespace must not match the intended ingress namespace selector."
    }
  }
}
output "owned" {
  value = {
    namespace    = kubernetes_namespace_v1.environment.metadata[0].name
    uid          = kubernetes_namespace_v1.environment.metadata[0].uid
    owner_digest = var.owner_digest
    ownedIds = {
      namespace = kubernetes_namespace_v1.environment.id
      policies  = [kubernetes_network_policy_v1.default_deny.id, kubernetes_network_policy_v1.same_namespace.id, kubernetes_network_policy_v1.dns.id, kubernetes_network_policy_v1.ingress.id]
      probes    = { for key, probe in kubernetes_pod_v1.probe : key => { id = probe.id, name = probe.metadata[0].name, namespace = probe.metadata[0].namespace, uid = probe.metadata[0].uid } }
    }
  }
}
