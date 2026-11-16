##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "resource" {
  type = object({
    provider       = string
    kind           = string
    subscriptionId = string
    resourceGroup  = string
    appName        = string
    containerName  = string
    ownership      = optional(string)
    os             = optional(string)
    architecture   = optional(string)
    iac = optional(object({
      managedEnvironmentId = optional(string)
    }))
  })
  validation {
    condition     = var.resource.kind == "azure.containerapps"
    error_message = "Wrong reviewed root for resource kind."
  }
}
variable "configuration" {
  type = object({
    kind    = string
    runtime = optional(string)
    iac = optional(object({
      managedEnvironmentId = optional(string)
      identityId           = optional(string)
      cpu                  = optional(number)
      memory               = optional(string)
    }))
  })
}
variable "workload" {
  type = object({ kind = string, port = number, healthPath = string })
}
variable "artifact" {
  description = "Immutable artifact verified and privately staged by the trusted executor."
  type = object({
    digest         = string
    format         = string
    path           = optional(string)
    imageReference = optional(string)
    files          = list(object({ path = string, key = string, contentType = string }))
  })
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.artifact.digest))
    error_message = "A verified immutable artifact digest is required."
  }
}
variable "owner_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.owner_digest))
    error_message = "A stable verified state ownership digest is required."
  }
}
locals { digest = substr(var.artifact.digest, 7, 64) }
