locals {
  {{- if .hub_spoke }}
  local_vars  = yamldecode(file("./inputs.yaml"))
  spoke_vars  = yamldecode(file(find_in_parent_folders("spoke-inputs.yaml")))
  region_vars = yamldecode(file(find_in_parent_folders("region-inputs.yaml")))
  env_vars    = yamldecode(file(find_in_parent_folders("env-inputs.yaml")))
  global_vars = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))

  local_tags  = jsondecode(file("./local-tags.json"))
  spoke_tags  = jsondecode(file(find_in_parent_folders("spoke-tags.json")))
  region_tags = jsondecode(file(find_in_parent_folders("region-tags.json")))
  env_tags    = jsondecode(file(find_in_parent_folders("env-tags.json")))
  global_tags = jsondecode(file(find_in_parent_folders("global-tags.json")))

  tags = merge(
    local.global_tags,
    local.env_tags,
    local.region_tags,
    local.spoke_tags,
    local.local_tags
  )
  {{- else }}
  local_vars  = yamldecode(file("./inputs.yaml"))
  global_vars = yamldecode(file(find_in_parent_folders("global-inputs.yaml")))
  global_tags = jsondecode(file(find_in_parent_folders("global-tags.json")))
  local_tags  = jsondecode(file("./local-tags.json"))

  tags = merge(
    local.global_tags,
    local.local_tags
  )
  {{- end }}
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "{{ .sourceUrl }}"
}

inputs = {
  # org = {
  #   organization_name = local.env_vars.org.organization_name
  #   organization_unit = local.env_vars.org.organization_unit
  #   environment_name  = local.env_vars.org.environment_name
  #   environment_type  = local.env_vars.org.environment_type
  # }
  org = local.env_vars.org
  {{- if .hub_spoke }}
  is_hub = {{ .is_hub }}
  spoke_def = local.spoke_vars.spoke_def
  {{- end}}
  ## Required
  {{- range .requiredVariables }}
  {{- if ne .Name "org" }}
  {{ .Name }} = try(local.local_vars.{{ .Name }}, {{ .DefaultValue }})
  {{- end }}
  {{- end }}

  ## Optional
  {{- range .optionalVariables }}
  {{- if ne .Name "extra_tags" "is_hub" "spoke_def" "org" }}
  {{ .Name }} = try(local.local_vars.{{ .Name }}, {{ .DefaultValue }})
  {{- end }}
  {{- end }}
  extra_tags = local.tags
}