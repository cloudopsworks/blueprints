mock_provider "google" {
  mock_data "google_project" { defaults = { number = "123456789" } }
  mock_data "google_storage_bucket" { defaults = { project_number = 123456789 } }
  mock_data "google_service_account" { defaults = { email = "runner@test-project.iam.gserviceaccount.com" } }
}
variables {
  owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  configuration = { "kind" : "gcp.storage-static" }
  workload      = { "kind" : "static" }
  artifact      = { "digest" : "sha256:68d88fe04869802d1c5369aee383f5a103d0388bb0aa4818386e9d4bbece31e6", "format" : "tar.gz", "path" : abspath("tests/index.html"), "imageReference" : null, "files" : [{ "path" : abspath("tests/index.html"), "key" : "index.html", "contentType" : "text/html" }] }
  resource      = { "kind" : "gcp.storage-static", "project" : "test-project", "region" : "us-central1", "bucket" : "external-bucket", "prefix" : "components/web" }
}
run "objectset" {
  command = plan
  assert {
    condition     = google_storage_bucket_object.files["index.html"].name == "components/web/index.html" && google_storage_bucket_object.files["index.html"].content_type == "text/html"
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}

run "owned_mock_apply" { command = apply }


run "reject_escaping_object" {
  command = plan
  variables {
    artifact = { digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", format = "tar.gz", path = null, imageReference = null, files = [{ path = abspath("tests/index.html"), key = "../escape", contentType = "text/html" }] }
  }
  expect_failures = [google_storage_bucket_object.files]
}

run "static_zip" {
  command = plan
  variables {
    artifact = { "digest" : "sha256:68d88fe04869802d1c5369aee383f5a103d0388bb0aa4818386e9d4bbece31e6", "format" : "zip", "path" : abspath("tests/index.html"), "imageReference" : null, "files" : [{ "path" : abspath("tests/index.html"), "key" : "index.html", "contentType" : "text/html" }] }
  }
  assert {
    condition     = google_storage_bucket_object.files["index.html"].name == "components/web/index.html"
    error_message = "ZIP extraction projection drifted."
  }
}
