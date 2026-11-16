# P0 schema/mock-plan proof only: mocks do not invoke cloud APIs.
mock_provider "aws" {
  mock_data "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/external" } }
  mock_data "aws_s3_bucket" { defaults = { id = "external-fixture" } }
}
mock_provider "google" {}
mock_provider "google-beta" {}
mock_provider "azurerm" {
  mock_data "azurerm_service_plan" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.Web/serverFarms/external" } }
  mock_data "azurerm_container_app_environment" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.App/managedEnvironments/external" } }
  mock_data "azurerm_user_assigned_identity" { defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/external/providers/Microsoft.ManagedIdentity/userAssignedIdentities/external" } }
}
mock_provider "kubernetes" {}
mock_provider "helm" {}

run "all_accepted_resource_shapes" {
  command = plan

  assert {
    condition     = aws_lambda_function.image.package_type == "Image" && aws_lambda_function.zip.package_type == "Zip"
    error_message = "Lambda ZIP and image must be separate resource configurations."
  }

  assert {
    condition     = azurerm_linux_function_app.image.site_config[0].application_stack[0].docker[0].image_name == "component@sha256" && azurerm_linux_function_app.image.site_config[0].application_stack[0].docker[0].image_tag == var.artifact_digest
    error_message = "The selected provider's digest split must survive schema planning."
  }

  assert {
    condition     = azurerm_resource_group_template_deployment.onedeploy.deployment_mode == "Incremental" && length(jsondecode(azurerm_resource_group_template_deployment.onedeploy.template_content).resources) == 1
    error_message = "Flex must use only the fixed incremental extension deployment."
  }
}

run "changed_zip_uses_digest_addressed_local_path" {
  command = plan
  variables {
    artifact_digest = "771c1eb88686788262e0aa5590b34a63502f0488083fc70888b019f128b0b781"
  }
  assert {
    condition     = endswith(azurerm_linux_web_app.zip.zip_deploy_file, "/artifacts/${var.artifact_digest}/released-package.zip") && endswith(azurerm_windows_web_app_slot.zip.zip_deploy_file, "/artifacts/${var.artifact_digest}/released-package.zip") && endswith(azurerm_linux_function_app.zip.zip_deploy_file, "/artifacts/${var.artifact_digest}/released-package.zip")
    error_message = "Changed bytes at the same transport filename must change the provider-visible path."
  }
  assert {
    condition     = endswith(jsondecode(azurerm_resource_group_template_deployment.onedeploy.parameters_content).packageUri.value, "/${var.artifact_digest}/released-package.zip?${var.package_read_sas}")
    error_message = "Flex package changes must change OneDeploy parameters; basename stays fixed."
  }
}


run "mismatched_package_bytes_block_plan" {
  command = plan
  variables {
    artifact_digest = "0000000000000000000000000000000000000000000000000000000000000000"
  }
  expect_failures = [azurerm_storage_blob.package]
}
