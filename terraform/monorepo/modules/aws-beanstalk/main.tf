##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Bounded primitives from the existing Beanstalk version/deploy split; all
# shared application, IAM, network and package bucket remain external.
data "aws_elastic_beanstalk_application" "external" { name = var.resource.application }
data "aws_elastic_beanstalk_solution_stack" "external" {
  most_recent = false
  name_regex  = var.configuration.iac.solutionStackName
  lifecycle {
    postcondition {
      condition     = self.name == var.configuration.iac.solutionStackName
      error_message = "Selected existing platform must match the exact reviewed solution stack."
    }
  }
}
data "aws_s3_bucket" "external" { bucket = var.resource.bucket }
data "aws_iam_role" "external" { name = element(reverse(split("/", var.configuration.iac.serviceRoleArn)), 0) }
data "aws_iam_instance_profile" "external" { name = var.configuration.iac.instanceProfileName }
data "aws_vpc" "external" { id = var.configuration.iac.vpcId }
data "aws_subnet" "external" {
  for_each = toset(var.configuration.iac.subnetIds)
  id       = each.value
}
data "aws_security_group" "external" {
  for_each = toset(var.configuration.iac.securityGroupIds)
  id       = each.value
}
resource "aws_s3_object" "package" {
  bucket      = data.aws_s3_bucket.external.id
  key         = "${trim(var.resource.prefix, "/")}/${local.digest}/application.zip"
  source      = var.artifact.path
  source_hash = local.digest
  tags        = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = var.artifact.format == "zip" && filesha256(var.artifact.path) == local.digest && var.workload.kind == "http"
      error_message = "Beanstalk requires the verified exact native or Dockerrun ZIP."
    }
    precondition {
      condition     = var.artifact.imageReference == null ? !strcontains(var.configuration.iac.solutionStackName, "Docker") : can(regex("@sha256:[0-9a-f]{64}$", var.artifact.imageReference)) && strcontains(var.configuration.iac.solutionStackName, "Docker")
      error_message = "Docker stack requires validated immutable Dockerrun ZIP projection; native ZIP requires native stack."
    }
  }
}
resource "aws_elastic_beanstalk_application_version" "component" {
  name         = local.digest
  application  = data.aws_elastic_beanstalk_application.external.name
  bucket       = aws_s3_object.package.bucket
  key          = aws_s3_object.package.key
  force_delete = false
  lifecycle { create_before_destroy = true }
}
locals {
  settings = {
    "service" = { namespace = "aws:elasticbeanstalk:environment", name = "ServiceRole", value = data.aws_iam_role.external.arn }
    "profile" = { namespace = "aws:autoscaling:launchconfiguration", name = "IamInstanceProfile", value = data.aws_iam_instance_profile.external.name }
    "vpc"     = { namespace = "aws:ec2:vpc", name = "VPCId", value = data.aws_vpc.external.id }
    "subnets" = { namespace = "aws:ec2:vpc", name = "Subnets", value = join(",", sort(var.configuration.iac.subnetIds)) }
    "groups"  = { namespace = "aws:autoscaling:launchconfiguration", name = "SecurityGroups", value = join(",", sort(var.configuration.iac.securityGroupIds)) }
  }
}
resource "aws_elastic_beanstalk_environment" "component" {
  name                = var.resource.environmentName
  application         = data.aws_elastic_beanstalk_application.external.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.external.name
  version_label       = aws_elastic_beanstalk_application_version.component.name
  dynamic "setting" {
    for_each = local.settings
    content {
      namespace = setting.value.namespace
      name      = setting.value.name
      value     = setting.value.value
    }
  }
  tags = { "cloudopsworks-owner" = var.owner_digest }
  lifecycle {
    precondition {
      condition     = var.configuration.kind == var.resource.kind && data.aws_iam_role.external.arn == var.configuration.iac.serviceRoleArn && length(var.configuration.iac.subnetIds) > 0 && length(var.configuration.iac.securityGroupIds) > 0 && alltrue([for subnet in data.aws_subnet.external : subnet.vpc_id == data.aws_vpc.external.id]) && alltrue([for group in data.aws_security_group.external : group.vpc_id == data.aws_vpc.external.id])
      error_message = "Shared service role and network must match selected existing parents."
    }
  }
}
output "owned" { value = { environmentId = aws_elastic_beanstalk_environment.component.id, environmentName = aws_elastic_beanstalk_environment.component.name, version = aws_elastic_beanstalk_application_version.component.name, endpoint = aws_elastic_beanstalk_environment.component.endpoint_url } }
