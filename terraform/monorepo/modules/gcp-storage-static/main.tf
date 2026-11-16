##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# As in the existing static upload primitive, own object keys, never the bucket,
# website or CDN. Verified extraction supplies exact local files and MIME types.
data "google_project" "external" { project_id = var.resource.project }
data "google_storage_bucket" "external" { name = var.resource.bucket }
resource "google_storage_bucket_object" "files" {
  for_each       = { for file in var.artifact.files : file.key => file }
  bucket         = data.google_storage_bucket.external.name
  name           = "${trim(var.resource.prefix, "/")}/${each.key}"
  source         = each.value.path
  content_type   = each.value.contentType
  source_md5hash = filemd5(each.value.path)
  metadata       = { "cloudopsworks-owner" = var.owner_digest, "cloudopsworks-artifact" = var.artifact.digest }
  lifecycle {
    precondition {
      condition     = contains(["zip", "tar.gz"], var.artifact.format) && var.workload.kind == "static"
      error_message = "Static content requires a verified extracted static archive."
    }
    precondition {
      condition     = length(trim(var.resource.prefix, "/")) > 0 && !contains(split("/", var.resource.prefix), "..") && !contains(split("/", var.resource.prefix), ".") && !strcontains(var.resource.prefix, "\\") && length(each.key) > 0 && !startswith(each.key, "/") && !contains(split("/", each.key), "..") && !contains(split("/", each.key), ".") && !strcontains(each.key, "\\")
      error_message = "Object keys must stay within the component-owned prefix."
    }
    precondition {
      condition     = tostring(data.google_storage_bucket.external.project_number) == data.google_project.external.number
      error_message = "External website bucket belongs to another project."
    }
  }
}
output "owned" { value = { objects = [for object in google_storage_bucket_object.files : object.id] } }
