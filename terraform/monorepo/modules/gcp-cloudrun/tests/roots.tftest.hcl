mock_provider "google" {
  mock_data "google_project" { defaults = { number = "123456789" } }
  mock_data "google_storage_bucket" { defaults = { project_number = 123456789 } }
  mock_data "google_service_account" { defaults = { email = "runner@test-project.iam.gserviceaccount.com" } }
}
variables {
  owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  configuration = { "kind" : "gcp.cloudrun", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }
  workload      = { "kind" : "http", "port" : 8080, "healthPath" : "/health" }
  artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "us-docker.pkg.dev/test-project/images/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
  resource      = { "kind" : "gcp.cloudrun", "project" : "test-project", "region" : "us-central1", "service" : "component" }
}
run "oci" {
  command = plan
  assert {
    condition     = google_cloud_run_v2_service.component.template[0].containers[0].image == var.artifact.imageReference && google_cloud_run_v2_service.component.template[0].containers[0].ports[0].container_port == 8080
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}

run "owned_mock_apply" { command = apply }


run "changed_http_port" {
  command = plan
  variables {
    workload = { kind = "http", port = 9090, healthPath = "/ready" }
  }
  assert {
    condition     = google_cloud_run_v2_service.component.template[0].containers[0].ports[0].container_port == 9090 && google_cloud_run_v2_service.component.template[0].containers[0].startup_probe[0].http_get[0].path == "/ready"
    error_message = "Immutable update or selected mode projection drifted."
  }
}

run "reject_tag_image" {
  command = plan
  variables {
    artifact = { digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", format = "oci", path = null, imageReference = "us-docker.pkg.dev/test-project/images/app:latest", files = [] }
  }
  expect_failures = [google_cloud_run_v2_service.component]
}
