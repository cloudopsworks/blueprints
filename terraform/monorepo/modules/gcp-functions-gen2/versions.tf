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
    google = { source = "hashicorp/google", version = "= 7.0.0" }
  }
}
