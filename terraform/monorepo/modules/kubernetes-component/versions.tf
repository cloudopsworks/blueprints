##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

terraform {
  required_version = "= 1.11.4"
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes", version = "= 2.38.0" }
    helm       = { source = "hashicorp/helm", version = "= 3.0.2" }
  }
}
provider "kubernetes" { config_path = var.kubeconfig_path }
provider "helm" { kubernetes = { config_path = var.kubeconfig_path } }
