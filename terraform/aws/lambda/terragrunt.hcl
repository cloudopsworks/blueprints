##
# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

locals {
  local_vars   = yamldecode(file("./inputs.yaml"))
  base_vars    = yamldecode(file("./inputs-global.yaml"))
  release_vars = yamldecode(file("./release.yaml"))
  global_vars  = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/cloudopsworks/terraform-module-aws-lambda-deploy.git//?ref=v5.4.4"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.local_vars.environment
  }
  namespace        = local.local_vars.environment
  versions_bucket  = local.local_vars.versions_bucket
  logs_bucket      = try(local.local_vars.logs_bucket, "")
  repository_owner = local.base_vars.repository_owner
  lambda           = local.local_vars.lambda
  release          = local.release_vars.release
  bucket_path      = local.release_vars.bucket_path
  version_label    = local.release_vars.version_label
  absolute_path    = get_terragrunt_dir()
  observability    = try(local.base_vars.observability, {})
  extra_tags       = try(local.local_vars.tags, {})
}