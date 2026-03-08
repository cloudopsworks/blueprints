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
  extra_tags = merge({
    "managed-by" = "iac"
    },
    try(local.local_vars.tags, {})
  )
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/cloudopsworks/terraform-module-aws-s3-static-content-deploy.git//?ref=v0.1.0-alpha.3"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.local_vars.environment
  }
  s3               = local.local_vars.s3
  repository_owner = local.base_vars.repository_owner
  release          = local.release_vars.release
  absolute_path    = local.release_vars.release_path
  extra_tags       = local.extra_tags
}