##
# (c) 2024 - Cloud Ops Works LLC - https://cloudops.works/
#            On GitHub: https://github.com/cloudopsworks
#            Distributed Under Apache v2.0 License
#
# on Plan generate plan files in each module
terraform {
  extra_arguments "plan_file" {
    commands  = ["plan"]
    arguments = ["-out=${get_terragrunt_dir()}/plan.tfplan"]
  }
}
# load local variables from state_conf.yaml
locals {
  state_conf  = yamldecode(file("./state_conf.yaml"))
  global_vars = yamldecode(file("./global-inputs.yaml"))
}

# Generate global provider block
generate "provider" {
  path      = "provider.g.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.global_vars.default.region}"
  assume_role {
    role_arn     = "${local.global_vars.default.sts_role_arn}"
    session_name = "terragrunt"
  }
}
EOF
}

# Generate remote state block
remote_state {
  backend = "s3"
  generate = {
    path      = "remote_state.g.tf"
    if_exists = "overwrite_terragrunt"
  }
  config = {
    bucket               = local.state_conf.s3.bucket
    region               = local.state_conf.s3.region
    workspace_key_prefix = "workspaces"
    encrypt              = true
    kms_key_id           = local.state_conf.s3.kms_key_id
    dynamodb_table       = local.state_conf.s3.dynamodb_table
    key                  = "deployments/${local.global_vars.environment}/${local.global_vars.release_name}/${path_relative_to_include()}/terraform.tfstate"
  }
}

terraform_version_constraint  = ">= 1.7 , <1.8"
terragrunt_version_constraint = ">= 0.58"