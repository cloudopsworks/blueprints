##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "resource" {
  type = object({ kind = string, project = string, region = string, service = string, iac = optional(object({ sourceBucket = string })) })
  validation {
    condition     = var.resource.kind == "gcp.appengine" && var.resource.service != "default"
    error_message = "App Engine requires the reviewed root and an exclusive nondefault service."
  }
}
variable "configuration" {
  type = object({
    kind = string
    iac  = object({ sourceBucket = optional(string), serviceAccount = string })
    appConfig = object({
      sourceDigest  = string
      service       = string
      runtime       = string
      environment   = string
      entrypoint    = optional(string)
      instanceClass = optional(string)
      runtimeConfig = optional(object({ operatingSystem = string, runtimeVersion = string }))
      scaling = optional(object({
        kind                        = string
        instances                   = optional(number)
        maxInstances                = optional(number)
        minInstances                = optional(number)
        idleTimeout                 = optional(string)
        targetCpuUtilization        = optional(number)
        targetThroughputUtilization = optional(number)
        maxConcurrentRequests       = optional(number)
        minIdleInstances            = optional(number)
        maxIdleInstances            = optional(number)
        minPendingLatency           = optional(string)
        maxPendingLatency           = optional(string)
      }))
    })
  })
  validation {
    condition     = contains(["standard", "flexible"], var.configuration.appConfig.environment)
    error_message = "App Engine environment must be standard or flexible."
  }
}
variable "workload" { type = object({ kind = string, port = number, healthPath = string }) }
variable "artifact" {
  description = "Immutable artifact, independently verified and staged by the trusted executor."
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
