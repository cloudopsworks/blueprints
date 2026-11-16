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
  type = object({ kind = string, provider = string, region = string, application = string, environmentName = string, bucket = string, prefix = string })
  validation {
    condition     = var.resource.kind == "aws.beanstalk" && var.resource.provider == "aws" && length(trim(var.resource.prefix, "/")) > 0 && !can(regex("(^|/)[.][.]?(/|$)|\\\\", var.resource.prefix))
    error_message = "Beanstalk requires an exact identity and safe component package prefix."
  }
}
variable "configuration" {
  type = object({ kind = string, iac = object({ solutionStackName = string, serviceRoleArn = string, instanceProfileName = string, vpcId = string, subnetIds = list(string), securityGroupIds = list(string) }) })
}
