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
  apis_vars    = yamldecode(file("./inputs-apis.yaml"))
  base_vars    = yamldecode(file("./inputs-global.yaml"))
  release_vars = yamldecode(file("./release.yaml"))
  global_vars  = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/cloudopsworks/terraform-module-aws-api-gateway-apis-deploy.git//?ref=v5.1.3"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.local_vars.environment
  }
  release           = local.release_vars.release
  cloud_provider    = local.apis_vars.provider
  apis              = local.apis_vars.apis
  api_files_dir     = try(local.global_vars.api_files_dir, "apifiles/")
  environment       = local.local_vars.environment
  aws_configuration = local.local_vars.aws
  apigw_definitions = local.local_vars.apigw_definitions
  absolute_path     = get_terragrunt_dir()
  extra_tags        = try(local.local_vars.tags, {})
}