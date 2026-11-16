##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "resource" {
  type = object({ kind = string, project = string, region = string, functionName = string, trigger = object({ kind = string, value = string }), iac = object({ sourceBucket = string }) })
  validation {
    condition     = var.resource.kind == "gcp.functions-gen2"
    error_message = "Wrong reviewed root for the selected resource kind."
  }
}
variable "configuration" { type = object({ kind = string, runtime = string, serviceAccount = string, iac = object({ sourceBucket = string, buildServiceAccount = string, entryPoint = string }), eventSource = optional(object({ source = string, resource = string })) }) }
variable "workload" { type = object({ kind = string }) }
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
