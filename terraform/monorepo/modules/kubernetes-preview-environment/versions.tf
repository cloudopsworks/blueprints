# Copyright 2026 Cloud Ops Works LLC. Apache-2.0.
terraform {
  required_version = "= 1.11.4"
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes", version = "= 2.38.0" }
  }
}
provider "kubernetes" { config_path = var.kubeconfig_path }
