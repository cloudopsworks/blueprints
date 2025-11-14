##
# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
locals {
  # region_arr        = split("-", data.google_project.current.id)
  # region            = format("%s%s%s", lower(local.region_arr[0]), lower(substr(local.region_arr[1], 0, 2)), lower(local.region_arr[2]))
  system_name       = format("%s-%s-%s-%s", lower(var.org.organization_unit), lower(var.org.environment_name), lower(var.org.environment_type), var.spoke_def)
  system_name_short = format("%s-%s-%s-%s", substr(lower(var.org.organization_unit), 0, 3), substr(lower(var.org.environment_name), 0, 3), substr(lower(replace(var.org.environment_type, "-", "")), 0, 4), var.spoke_def)
  system_name_sub30 = format("%s-%s-%s-%s", substr(lower(var.org.organization_unit), 0, 1), substr(lower(var.org.environment_name), 0, 1), substr(lower(replace(var.org.environment_type, "-", "")), 0, 4), var.spoke_def)
  system_name_env   = format("%s-%s", substr(lower(replace(var.org.environment_type, "-", "")), 0, 4), var.spoke_def)
  std_tags          = merge(module.tags.locals.common_tags, var.extra_tags)
  all_tags          = {for k, v in local.std_tags: lower(k) => replace(lower(v), "/[ //@#$+=.]/", "_")}
  secret_store_path = format("/%s/%s/%s", lower(var.org.organization_unit), lower(var.org.environment_name), lower(var.org.environment_type))

}
