##
# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

locals {
  local_vars   = yamldecode(file("./inputs-api.yaml"))
  cloud_vars   = yamldecode(file("./inputs-cloud.yaml"))
  base_vars    = yamldecode(file("./inputs-base.yaml"))
  release_vars = yamldecode(file(find_in_parent_folders("./release.yaml")))
  global_vars  = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/cloudopsworks/terraform-module-aws-api-gateway-apis-deploy.git//?ref=v6.0.21"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.cloud_vars.environment
  }
  release           = local.release_vars.release
  api_files_dir     = "../../apifiles/"
  environment       = local.cloud_vars.environment
  aws_configuration = local.cloud_vars.aws
  apigw_definition  = local.local_vars
  absolute_path     = get_terragrunt_dir()
  cloud_type        = local.global_vars.cloud_type
  extra_tags        = try(local.cloud_vars.tags, {})
}