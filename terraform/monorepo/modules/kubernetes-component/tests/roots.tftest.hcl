mock_provider "kubernetes" {}
mock_provider "helm" {}
variables {
  resource          = { kind = "aws.eks", namespace = "apps" }
  configuration     = { kind = "aws.eks" }
  workload          = { kind = "http", port = 8080, healthPath = "/health" }
  artifact          = { digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", format = "oci", imageReference = "registry.example.com/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  owner_digest      = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  release_name      = "api"
  chart_path        = "../../../../kubernetes/helm/charts"
  kubeconfig_path   = "/unused-mocked-kubeconfig"
  readiness_seconds = 120
}
run "eks_immutable_release" {
  command = plan
  assert {
    condition     = helm_release.component.name == "api" && !helm_release.component.create_namespace && helm_release.component.description == var.owner_digest && helm_release.component.atomic && !helm_release.component.reuse_values
    error_message = "Owned release must not adopt/create an external namespace or reuse untrusted values."
  }
  assert {
    condition     = jsondecode(helm_release.component.values[0]).monorepo.image == var.artifact.imageReference && jsondecode(helm_release.component.values[0]).monorepo.port == 8080 && !jsondecode(helm_release.component.values[0]).monorepo.preview
    error_message = "Authoritative chart receives only the exact normal workload image and generated values."
  }
}
run "gke" {
  command = plan
  variables {
    resource      = { kind = "gcp.gke", namespace = "apps" }
    configuration = { kind = "gcp.gke" }
  }
}
run "aks" {
  command = plan
  variables {
    resource      = { kind = "azure.aks", namespace = "apps" }
    configuration = { kind = "azure.aks" }
  }
}
run "owned_mock_apply" { command = apply }
run "reject_mutable_tag" {
  command = plan
  variables {
    artifact = { digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", format = "oci", imageReference = "registry.example.com/app:latest" }
  }
  expect_failures = [helm_release.component]
}
run "reject_family_override" {
  command = plan
  variables { configuration = { kind = "azure.aks" } }
  expect_failures = [helm_release.component]
}
