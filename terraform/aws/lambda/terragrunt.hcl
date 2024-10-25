##
# (c) 2024 - Cloud Ops Works LLC - https://cloudops.works/
#            On GitHub: https://github.com/cloudopsworks
#            Distributed Under Apache v2.0 License
#

locals {
  local_vars   = yamldecode(file("./inputs.yaml"))
  base_vars    = yamldecode(file("./inputs-global.yaml"))
  release_vars = yamldecode(file("./release.yaml"))
  global_vars  = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))
}

include {
  path = find_in_parent_folders()
}

terraform {
  source = "github.com/cloudopsworks/terraform-module-aws-lambda-deploy.git//?ref=v5"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.local_vars.environment
  }
  namespace        = local.local_vars.environment
  repository_owner = local.base_vars.repository_owner
  lambda           = local.local_vars.lambda
  release          = local.release_vars.release
  absolute_path    = get_terragrunt_dir()
  extra_tags       = try(local.local_vars.tags, {})
}