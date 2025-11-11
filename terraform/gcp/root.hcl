##
# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
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
  state_conf        = yamldecode(file("./state_conf.yaml"))
  global_vars       = yamldecode(file("./global-inputs.yaml"))
  state_prefix      = "deployments/${local.global_vars.environment}/${local.global_vars.release_name}/${path_relative_to_include()}"
  remote_state_type = keys(local.state_conf)[0]
}

# Generate global provider block
generate "provider" {
  path      = "provider.g.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "google" {
  project                     = "${local.global_vars.default.project}"
  region                      = "${local.global_vars.default.region}"
  impersonate_service_account = "${local.global_vars.default.impersonate_sa}"
}
provider "google-beta" {
  project                     = "${local.global_vars.default.project}"
  region                      = "${local.global_vars.default.region}"
  impersonate_service_account = "${local.global_vars.default.impersonate_sa}"
}
EOF
}

# Generate remote state block
generate "backend" {
  path      = "remote_state.g.tf"
  if_exists = "overwrite_terragrunt"
  content = local.remote_state_type == "s3" ? join("\n", [
    "terraform {",
    "  backend \"s3\" {",
    "    bucket         = \"${local.state_conf.s3.bucket}\"",
    "    region         = \"${local.state_conf.s3.region}\"",
    "    kms_key_id     = \"${local.state_conf.s3.kms_key_id}\"",
    "    dynamodb_table = \"${local.state_conf.s3.dynamodb_table}\"",
    "    key            = \"$(local.state_prefix}/terraform.tfstate\"",
    "  }",
    "}",
    ]) : (local.remote_state_type == "gcs" ? join("\n", [
      "terraform {",
      "  backend \"gcs\" {",
      "    bucket             = \"${local.state_conf.gcs.bucket}\"",
      "    kms_encryption_key = \"${local.state_conf.gcs.kms_encryption_key}\"",
      "    prefix             = \"${local.state_prefix}/terraform.tfstate\"",
      "  }",
      "}",
      ]) : (local.remote_state_type == "azurerm" ? join("\n", [
        "terraform {",
        "  backend \"azurerm\" {",
        "    use_msi              = true",
        "    use_azuread_auth     = true",
        "    tenant_id            = \"${local.state_conf.azurerm.tenant_id}\"",
        "    subscription_id      = \"${local.state_conf.azurerm.subscription_id}\"",
        "    resource_group_name  = \"${local.state_conf.azurerm.resource_group_name}\"",
        "    storage_account_name = \"${local.state_conf.azurerm.storage_account_name}\"",
        "    container_name       = \"${local.state_conf.azurerm.container_name}\"",
        "    key                  = \"${local.state_prefix}/terraform.tfstate\"",
        "  }",
        "}",
    ]) : "")
  )
}

terraform_version_constraint  = ">= 1.9 , <=1.11"
terragrunt_version_constraint = ">= 0.88"