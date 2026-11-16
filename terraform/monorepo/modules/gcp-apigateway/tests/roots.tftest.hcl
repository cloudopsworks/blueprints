mock_provider "google-beta" {
  mock_data "google_project" { defaults = { number = "123456789" } }
}
variables {
  owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  configuration = { "kind" : "gcp.apigateway" }
  workload      = { "kind" : "api" }
  artifact      = { "digest" : "sha256:1477113b607d858107e1b1ceaeb3ba5ac29a412e785b7978583b2984ca77a3d6", "format" : "yaml", "path" : abspath("tests/openapi.yaml"), "imageReference" : null, "files" : [] }
  resource      = { "kind" : "gcp.apigateway", "project" : "test-project", "region" : "us-central1", "api" : "component", "gateway" : "component", "backendServiceAccount" : "runner@test-project.iam.gserviceaccount.com" }
}
run "openapi" {
  command = plan
  assert {
    condition     = google_api_gateway_api.component.api_id == "component" && google_api_gateway_api_config.component.openapi_documents[0].document[0].contents == filebase64(var.artifact.path)
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}

run "owned_mock_apply" { command = apply }


run "openapi_json" {
  command = plan
  variables {
    artifact = { digest = "sha256:deb57e456af6a26f3b63a5cfe58634a6aad798ccc7957c043ce594c5b56d1f0b", format = "json", path = abspath("tests/openapi.json"), imageReference = null, files = [] }
  }
  assert {
    condition     = google_api_gateway_api_config.component.openapi_documents[0].document[0].path == "openapi.json" && google_api_gateway_api_config.component.openapi_documents[0].document[0].contents == filebase64(var.artifact.path)
    error_message = "Immutable update or selected mode projection drifted."
  }
}

run "reject_openapi_digest" {
  command = plan
  variables {
    artifact = { digest = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", format = "json", path = abspath("tests/openapi.json"), imageReference = null, files = [] }
  }
  expect_failures = [google_api_gateway_api_config.component]
}
