mock_provider "google" {
  mock_data "google_project" { defaults = { number = "123456789" } }
  mock_data "google_storage_bucket" { defaults = { project_number = 123456789 } }
  mock_data "google_service_account" { defaults = { email = "runner@test-project.iam.gserviceaccount.com" } }
}
variables {
  owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  configuration = { "kind" : "gcp.functions-gen2", "runtime" : "python313", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com", "iac" : { "sourceBucket" : "external-bucket", "buildServiceAccount" : "projects/test-project/serviceAccounts/build@test-project.iam.gserviceaccount.com", "entryPoint" : "main" } }
  workload      = { "kind" : "function" }
  artifact      = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : abspath("tests/package.zip"), "imageReference" : null, "files" : [] }
  resource      = { "kind" : "gcp.functions-gen2", "project" : "test-project", "region" : "us-central1", "functionName" : "component", "trigger" : { "kind" : "http", "value" : "" }, "iac" : { "sourceBucket" : "external-bucket" } }
}
run "http" {
  command = plan
  assert {
    condition     = length(google_cloudfunctions2_function.component.event_trigger) == 0 && strcontains(google_storage_bucket_object.package.name, substr(var.artifact.digest, 7, 64))
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}
run "pubsub" {
  command = plan
  variables {
    resource      = { "kind" : "gcp.functions-gen2", "project" : "test-project", "region" : "us-central1", "functionName" : "component", "trigger" : { "kind" : "eventarc", "value" : "projects/test-project/topics/external" }, "iac" : { "sourceBucket" : "external-bucket" } }
    configuration = { "kind" : "gcp.functions-gen2", "runtime" : "python313", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com", "iac" : { "sourceBucket" : "external-bucket", "buildServiceAccount" : "projects/test-project/serviceAccounts/build@test-project.iam.gserviceaccount.com", "entryPoint" : "main" }, "eventSource" : { "source" : "pubsub", "resource" : "projects/test-project/topics/external" } }
  }
  assert {
    condition     = google_cloudfunctions2_function.component.event_trigger[0].event_type == "google.cloud.pubsub.topic.v1.messagePublished"
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}
run "storage_finalize" {
  command = plan
  variables {
    resource      = { "kind" : "gcp.functions-gen2", "project" : "test-project", "region" : "us-central1", "functionName" : "component", "trigger" : { "kind" : "eventarc", "value" : "external-events" }, "iac" : { "sourceBucket" : "external-bucket" } }
    configuration = { "kind" : "gcp.functions-gen2", "runtime" : "python313", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com", "iac" : { "sourceBucket" : "external-bucket", "buildServiceAccount" : "projects/test-project/serviceAccounts/build@test-project.iam.gserviceaccount.com", "entryPoint" : "main" }, "eventSource" : { "source" : "storage-finalize", "resource" : "external-events" } }
  }
  assert {
    condition     = google_cloudfunctions2_function.component.event_trigger[0].event_type == "google.cloud.storage.object.v1.finalized"
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}

run "owned_mock_apply" { command = apply }


run "changed_package" {
  command = plan
  variables {
    artifact = { digest = "sha256:730191a756b76e72981480fdb102bb4292c19e7831acdd474b5b32a74d7d3dd6", format = "zip", path = abspath("tests/changed-package.zip"), imageReference = null, files = [] }
  }
  assert {
    condition     = google_storage_bucket_object.package.name == "cloudopsworks/${substr(var.owner_digest, 7, 64)}/730191a756b76e72981480fdb102bb4292c19e7831acdd474b5b32a74d7d3dd6/main.zip" && !strcontains(google_storage_bucket_object.package.name, "b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351")
    error_message = "Immutable update or selected mode projection drifted."
  }
}

run "reject_digest_mismatch" {
  command = plan
  variables {
    artifact = { digest = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", format = "zip", path = abspath("tests/changed-package.zip"), imageReference = null, files = [] }
  }
  expect_failures = [google_storage_bucket_object.package]
}
