##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "workload" { type = object({ kind = string }) }
variable "artifact" {
  type = object({ digest = string, format = string, path = optional(string), imageReference = optional(string), files = list(object({ path = string, key = string, contentType = string })) })
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.artifact.digest))
    error_message = "Artifact requires an exact immutable SHA256 descriptor."
  }
}
variable "owner_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.owner_digest))
    error_message = "Verified stable state ownership digest is required."
  }
}
locals { digest = substr(var.artifact.digest, 7, 64) }
variable "resource" {
  type = object({ kind = string, provider = string, region = string, restApiId = optional(string), stage = string, ownership = optional(string), apiName = optional(string), apiVersion = optional(string) })
  validation {
    condition     = var.resource.kind == "aws.apigateway-rest" && var.resource.provider == "aws" && var.resource.ownership == "managed"
    error_message = "Native API root requires managed identity; existing IDs require independently verified owned state, never import."
  }
}
variable "configuration" { type = object({ kind = string }) }

variable "resolved_api" {
  description = "Existing-ID only: name and description independently verified against exact private state, provider GET and owner proof; never user config."
  type        = object({ name = string, description = string })
  default     = null
  nullable    = true
}
