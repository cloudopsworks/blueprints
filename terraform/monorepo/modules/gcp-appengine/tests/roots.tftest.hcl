mock_provider "google" {
  mock_data "google_project" { defaults = { number = "123456789" } }
  mock_data "google_storage_bucket" { defaults = { project_number = 123456789 } }
  mock_data "google_service_account" { defaults = { email = "runner@test-project.iam.gserviceaccount.com" } }
}
variables {
  owner_digest  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "standard", "scaling" : { "kind" : "manual", "instances" : 1 } } }
  workload      = { "kind" : "http", "port" : 8080, "healthPath" : "/health" }
  artifact      = { "digest" : "sha256:b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351", "format" : "zip", "path" : abspath("tests/package.zip"), "imageReference" : null, "files" : [] }
  resource      = { "kind" : "gcp.appengine", "project" : "test-project", "region" : "us-central1", "service" : "component", "iac" : { "sourceBucket" : "external-bucket" } }
}
run "standard_native" {
  command = plan
  assert {
    condition     = google_app_engine_standard_app_version.component[0].delete_service_on_destroy == true && google_app_engine_standard_app_version.component[0].noop_on_destroy == false && google_storage_bucket_object.package[0].name == "cloudopsworks/${substr(var.owner_digest, 7, 64)}/${substr(var.artifact.digest, 7, 64)}/main.zip"
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}
run "flex_native" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python", "environment" : "flexible", "scaling" : { "kind" : "automatic", "minInstances" : 1, "maxInstances" : 2, "targetCpuUtilization" : 0.6 }, "runtimeConfig" : { "operatingSystem" : "ubuntu22", "runtimeVersion" : "3.13" } } }
  }
  assert {
    condition     = google_app_engine_flexible_app_version.component[0].automatic_scaling[0].cpu_utilization[0].target_utilization == 0.6
    error_message = "Owned workload or immutable artifact projection drifted."
  }
}
run "flex_oci" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "custom", "environment" : "flexible", "scaling" : { "kind" : "manual", "instances" : 1 }, "runtimeConfig" : null } }
    artifact      = { "digest" : "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "format" : "oci", "path" : null, "imageReference" : "us-docker.pkg.dev/test-project/images/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "files" : [] }
  }
  assert {
    condition     = google_app_engine_flexible_app_version.component[0].deployment[0].container[0].image == var.artifact.imageReference && length(google_storage_bucket_object.package) == 0
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
    condition     = google_storage_bucket_object.package[0].name == "cloudopsworks/${substr(var.owner_digest, 7, 64)}/730191a756b76e72981480fdb102bb4292c19e7831acdd474b5b32a74d7d3dd6/main.zip" && !strcontains(google_storage_bucket_object.package[0].name, "b9837f23dbee9254a400c2b1d1c0d733d553aa00c5c5e29062f7f783cbe37351")
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

run "standard_basic" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "standard", "scaling" : { "kind" : "basic", "maxInstances" : 2, "idleTimeout" : "60s" } } }
  }
  assert {
    condition     = google_app_engine_standard_app_version.component[0].basic_scaling[0].max_instances == 2
    error_message = "Immutable update or selected mode projection drifted."
  }
}

run "standard_automatic" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "standard", "scaling" : { "kind" : "automatic", "minInstances" : 0, "maxInstances" : 2, "targetCpuUtilization" : 0.5, "targetThroughputUtilization" : 0.6 } } }
  }
  assert {
    condition     = google_app_engine_standard_app_version.component[0].automatic_scaling[0].standard_scheduler_settings[0].target_throughput_utilization == 0.6
    error_message = "Immutable update or selected mode projection drifted."
  }
}

run "reject_default_service" {
  command = plan
  variables {
    resource      = { "kind" : "gcp.appengine", "project" : "test-project", "region" : "us-central1", "service" : "default", "iac" : { "sourceBucket" : "external-bucket" } }
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "default", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "standard", "scaling" : { "kind" : "manual", "instances" : 1 } } }
  }
  expect_failures = [var.resource]
}

run "reject_unknown_environment" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "custom", "scaling" : { "kind" : "manual", "instances" : 1 } } }
  }
  expect_failures = [var.configuration]
}

run "reject_service_config_mismatch" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "foreign", "runtime" : "python313", "entrypoint" : "gunicorn main:app", "environment" : "standard", "scaling" : { "kind" : "manual", "instances" : 1 } } }
  }
  expect_failures = [google_app_engine_standard_app_version.component]
}

run "reject_flexible_basic_scaling" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python", "entrypoint" : "gunicorn main:app", "environment" : "flexible", "scaling" : { "kind" : "basic", "maxInstances" : 2, "idleTimeout" : "60s" }, "runtimeConfig" : { "operatingSystem" : "ubuntu22", "runtimeVersion" : "3.13" } } }
  }
  expect_failures = [google_app_engine_flexible_app_version.component]
}

run "reject_flexible_throughput" {
  command = plan
  variables {
    configuration = { "kind" : "gcp.appengine", "iac" : { "sourceBucket" : "external-bucket", "serviceAccount" : "runner@test-project.iam.gserviceaccount.com" }, "appConfig" : { "sourceDigest" : "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "service" : "component", "runtime" : "python", "entrypoint" : "gunicorn main:app", "environment" : "flexible", "scaling" : { "kind" : "automatic", "minInstances" : 1, "maxInstances" : 2, "targetCpuUtilization" : 0.6, "targetThroughputUtilization" : 0.5 }, "runtimeConfig" : { "operatingSystem" : "ubuntu22", "runtimeVersion" : "3.13" } } }
  }
  expect_failures = [google_app_engine_flexible_app_version.component]
}
