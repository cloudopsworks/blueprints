##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Fixed internal values, generated only from verified canonical operation data.
variable "resource" {
  type = object({
    kind        = string, provider = string, region = string, functionName = string,
    packageMode = string, alias = optional(string), architecture = optional(string, "x86_64"),
    iac         = optional(object({ sourceBucket = optional(string), sourcePrefix = optional(string) }), {})
  })
  validation {
    condition     = var.resource.kind == "aws.lambda" && var.resource.provider == "aws" && contains(["zip", "image"], var.resource.packageMode)
    error_message = "Only reviewed Lambda ZIP and image package modes are supported."
  }
}
variable "configuration" {
  type = object({ kind = string, runtime = optional(string), iac = object({ roleArn = string }) })
}
variable "artifact" {
  type = object({ digest = string, format = string, path = optional(string), imageReference = optional(string), files = list(object({ path = string, key = string, contentType = string })) })
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.artifact.digest))
    error_message = "Artifact requires an exact immutable SHA256 descriptor."
  }
}
variable "package_handler" {
  type     = string
  default  = null
  nullable = true
}
variable "owner_digest" { type = string }
locals {
  region          = var.resource.region
  function_name   = var.resource.functionName
  role_arn        = var.configuration.iac.roleArn
  package_mode    = var.resource.packageMode
  runtime         = var.configuration.runtime
  handler         = var.package_handler
  architecture    = var.resource.architecture
  source_bucket   = var.resource.iac.sourceBucket
  source_prefix   = coalesce(var.resource.iac.sourcePrefix, "components")
  package_path    = var.artifact.path
  artifact_digest = var.artifact.digest
  image_reference = var.artifact.imageReference
  alias           = var.resource.alias
}

# Component-owned function/alias/package objects only. IAM and bucket are external.
data "aws_caller_identity" "external" {}
data "aws_iam_role" "external" {
  name = element(reverse(split("/", local.role_arn)), 0)
}
data "aws_s3_bucket" "external" {
  count  = local.package_mode == "zip" ? 1 : 0
  bucket = local.source_bucket
}
resource "aws_s3_object" "package" {
  count       = local.package_mode == "zip" ? 1 : 0
  bucket      = data.aws_s3_bucket.external[0].id
  key         = "${trim(local.source_prefix, "/")}/${substr(local.artifact_digest, 7, 64)}/main.zip"
  source      = local.package_path
  source_hash = substr(local.artifact_digest, 7, 64)
  tags        = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = try(filesha256(local.package_path) == substr(local.artifact_digest, 7, 64), false)
      error_message = "Staged package bytes disagree with immutable artifact digest."
    }
  }
}
resource "aws_lambda_function" "component" {
  function_name     = local.function_name
  role              = data.aws_iam_role.external.arn
  package_type      = local.package_mode == "zip" ? "Zip" : "Image"
  architectures     = [local.architecture]
  runtime           = local.package_mode == "zip" ? local.runtime : null
  handler           = local.package_mode == "zip" ? local.handler : null
  image_uri         = local.package_mode == "image" ? local.image_reference : null
  s3_bucket         = local.package_mode == "zip" ? data.aws_s3_bucket.external[0].id : null
  s3_key            = local.package_mode == "zip" ? aws_s3_object.package[0].key : null
  s3_object_version = local.package_mode == "zip" ? aws_s3_object.package[0].version_id : null
  source_code_hash  = local.package_mode == "zip" ? filebase64sha256(local.package_path) : null
  publish           = true
  tags              = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = data.aws_iam_role.external.arn == local.role_arn
      error_message = "Resolved external role does not match protected role identity."
    }
    precondition {
      condition     = local.package_mode != "zip" || (local.runtime != null && local.handler != null)
      error_message = "ZIP execution requires an explicitly verified runtime and package handler."
    }
    precondition {
      condition     = local.package_mode != "image" || try(can(regex("^${data.aws_caller_identity.external.account_id}\\.dkr\\.ecr\\.${local.region}\\.amazonaws\\.com/[a-z0-9][a-z0-9/_-]*@${local.artifact_digest}$", local.image_reference)), false)
      error_message = "Lambda image must use exact digest in the resolved account and region private ECR."
    }
  }
}
resource "aws_lambda_alias" "component" {
  count            = local.alias == null ? 0 : 1
  name             = local.alias
  function_name    = aws_lambda_function.component.function_name
  function_version = aws_lambda_function.component.version
}
output "owned" {
  value = { function_arn = aws_lambda_function.component.arn, version = aws_lambda_function.component.version }
}
