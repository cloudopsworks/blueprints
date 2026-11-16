##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Fresh API ownership only. Existing IDs are accepted only by the shared verified
# state gate; this root deliberately contains no import/adoption automation.
resource "aws_api_gateway_rest_api" "component" {
  name              = var.resource.restApiId == null ? var.resource.apiName : try(var.resolved_api.name, null)
  description       = var.resource.restApiId == null ? "Component API ${var.resource.apiVersion}" : try(var.resolved_api.description, null)
  body              = file(var.artifact.path)
  put_rest_api_mode = "overwrite"
  fail_on_warnings  = true
  tags              = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = var.resource.restApiId == null ? var.resource.apiName != null && var.resource.apiVersion != null && var.resolved_api == null : var.resolved_api != null
      error_message = "Fresh APIs require explicit name/version; existing IDs require independently verified private-state/API/owner projection."
    }
    precondition {
      condition     = contains(["yaml", "json"], var.artifact.format) && var.workload.kind == "api" && var.configuration.kind == var.resource.kind && filesha256(var.artifact.path) == local.digest && var.artifact.imageReference == null
      error_message = "API requires exact immutable OpenAPI bytes."
    }
    postcondition {
      condition     = var.resource.restApiId == null || self.id == var.resource.restApiId
      error_message = "Existing API identity must match verified owned native state."
    }
  }
}
resource "aws_api_gateway_deployment" "component" {
  rest_api_id = aws_api_gateway_rest_api.component.id
  triggers    = { artifact = var.artifact.digest, specification = filesha256(var.artifact.path), api_version = var.resource.apiVersion == null ? "" : var.resource.apiVersion }
  lifecycle { create_before_destroy = true }
}
resource "aws_api_gateway_stage" "component" {
  rest_api_id   = aws_api_gateway_rest_api.component.id
  deployment_id = aws_api_gateway_deployment.component.id
  stage_name    = var.resource.stage
  tags          = { "cloudopsworks-owner" = var.owner_digest }
}
output "owned" { value = { restApiId = aws_api_gateway_rest_api.component.id, deploymentId = aws_api_gateway_deployment.component.id, stage = aws_api_gateway_stage.component.stage_name, invokeUrl = aws_api_gateway_stage.component.invoke_url } }
