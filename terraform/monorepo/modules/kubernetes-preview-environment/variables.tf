# Copyright 2026 Cloud Ops Works LLC. Apache-2.0.
variable "resource" { type = object({ kind = string, namespace = string }) }
variable "configuration" { type = object({ kind = string }) }
variable "workload" { type = object({ kind = string }) }
variable "owner_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.owner_digest))
    error_message = "The immutable environment state owner digest is required."
  }
}
variable "namespace" {
  description = "Exact namespace from the sole validated Go StateHandle, never an override."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.namespace))
    error_message = "Preview namespace must be a valid bounded Kubernetes name."
  }
}
variable "repository_id" {
  type = string
  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.repository_id))
    error_message = "Verified numeric repository ID is required."
  }
}
variable "pr_number" {
  type = number
  validation {
    condition     = var.pr_number >= 1 && var.pr_number <= 2147483647 && floor(var.pr_number) == var.pr_number
    error_message = "Verified positive integer PR number is required."
  }
}
variable "target_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,47}$", var.target_id))
    error_message = "Verified target ID is required."
  }
}
variable "kubeconfig_path" { type = string }
variable "isolation" {
  description = "Closed protected-policy projection; ingressNamespace is independently uniquely API-resolved. No PR commands, scripts or arbitrary manifests."
  type = object({
    probeImage               = string
    controlNamespace         = string
    ingressNamespace         = string
    ingressNamespaceSelector = map(string)
    ingressPodSelector       = map(string)
    dnsNamespaceSelector     = map(string)
    dnsPodSelector           = map(string)
  })
  validation {
    condition = alltrue([for name in [var.isolation.controlNamespace, var.isolation.ingressNamespace] : can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", name))]) && !strcontains(var.isolation.probeImage, "://") && can(regex("^[^[:space:]]+@sha256:[0-9a-f]{64}$", var.isolation.probeImage)) && alltrue([
      for selector in [var.isolation.ingressNamespaceSelector, var.isolation.ingressPodSelector, var.isolation.dnsNamespaceSelector, var.isolation.dnsPodSelector] :
      length(selector) > 0 && alltrue([for key, value in selector : length(key) > 0 && length(value) > 0])
    ])
    error_message = "Probe image must be immutable and protected selectors must not match every namespace/pod."
  }
}
