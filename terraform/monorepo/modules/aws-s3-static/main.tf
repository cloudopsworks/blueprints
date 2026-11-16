##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# Existing static upload primitive: object ownership only, never bucket/website/CDN.
data "aws_s3_bucket" "external" { bucket = var.resource.bucket }
resource "aws_s3_object" "files" {
  for_each     = { for file in var.artifact.files : file.key => file }
  bucket       = data.aws_s3_bucket.external.id
  key          = "${trim(var.resource.prefix, "/")}/${each.key}"
  source       = each.value.path
  source_hash  = filesha256(each.value.path)
  content_type = each.value.contentType
  tags         = { "cloudopsworks-owner" = var.owner_digest, "cloudopsworks-artifact" = var.artifact.digest }
  lifecycle {
    precondition {
      condition     = var.workload.kind == "static" && var.configuration.kind == var.resource.kind && contains(["zip", "tar.gz"], var.artifact.format) && length(var.artifact.files) > 0
      error_message = "Static requires a verified extracted immutable archive."
    }
    precondition {
      condition     = length(each.key) > 0 && !startswith(each.key, "/") && !can(regex("(^|/)[.][.]?(/|$)|\\\\", each.key))
      error_message = "Object key escapes the component prefix."
    }
  }
}
output "owned" { value = { objects = [for object in aws_s3_object.files : object.id] } }
