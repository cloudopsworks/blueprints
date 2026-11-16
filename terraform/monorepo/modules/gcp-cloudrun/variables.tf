##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "resource" {
  type = object({ kind = string, project = string, region = string, service = string })
  validation {
    condition     = var.resource.kind == "gcp.cloudrun"
    error_message = "Wrong reviewed root for the selected resource kind."
  }
}
variable "configuration" { type = object({ kind = string, serviceAccount = string }) }
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
