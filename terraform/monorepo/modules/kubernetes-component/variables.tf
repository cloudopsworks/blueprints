##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

variable "resource" { type = object({ kind = string, namespace = string }) }
variable "configuration" { type = object({ kind = string }) }
variable "workload" { type = object({ kind = string, port = number, healthPath = string }) }
variable "artifact" { type = object({ digest = string, format = string, imageReference = string }) }
variable "owner_digest" { type = string }
variable "release_name" { type = string }
variable "chart_path" { type = string }
variable "kubeconfig_path" { type = string }
variable "readiness_seconds" { type = number }

# Derived only from the trusted preview policy and sole Go namespace.
variable "preview_options" {
  type    = object({ host = string, ingressClass = string })
  default = null
}
