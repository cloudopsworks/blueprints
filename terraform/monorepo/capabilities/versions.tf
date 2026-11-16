##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#

# P0 capability workbench only. It has no backend and is not an execution root.
terraform {
  required_version = "= 1.11.4"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.35.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "= 7.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "= 7.0.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.66.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "= 2.38.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "= 3.0.2"
    }
  }
}
