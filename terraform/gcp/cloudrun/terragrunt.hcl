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
  source = "git::https://github.com/cloudopsworks/terraform-module-gcp-cloudrun-deploy.git//?ref=v1.0.0"
}

inputs = {
  org = {
    organization_name = local.base_vars.organization_name
    organization_unit = local.base_vars.organization_unit
    environment_name  = local.base_vars.environment_name
    environment_type  = local.local_vars.environment
  }
  repository_owner   = local.base_vars.repository_owner
  namespace          = local.local_vars.environment
  region             = local.global_vars.default.region
  cloudrun           = local.local_vars.cloudrun
  container_registry = local.local_vars.container_registry
  dns                = local.local_vars.dns
  alarms             = local.local_vars.alarms
  release            = local.release_vars.release
  observability      = try(local.base_vars.observability, {})
  deployment_sa      = try(local.global_vars.default.impersonate_sa, null)
  extra_tags         = try(local.local_vars.tags, {})
}