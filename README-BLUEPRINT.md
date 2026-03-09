# Blueprint GitHub Actions Documentation

This document provides a comprehensive overview of all GitHub Action composites available in this repository.

## Table of Contents
- [CD](#cd)
- [CI](#ci)

## CD

### Checkout Code & Blueprint here

**Path**: `./cd/checkout/action.yml`

Checkout the code and blueprint for the current branch

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_ref` | The branch or tag to checkout | false | `${{ github.ref }}` |
| `blueprint_ref` | The branch or tag to checkout | false | `v5.10` |
| `token` | The GitHub token | false | `` |

#### What it performs
- Checkout Source Code
- Checkout Source Code w/PAT
- Checkout Blueprint
- Check Source Module version

---

### Check Module Versions and warn if not latest

**Path**: `./cd/checkout/check-module-version/action.yml`

Check the module versions and warn if not latest

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | true | `source` |
| `blueprint_path` | The path to the blueprint | true | `bp` |
| `token` | The GitHub token | false | `` |

#### What it performs
- Restore Cache
- Check Module Type
- Check Blueprint Version
- Check Module Version
- Save Check Beacon
- Save Cache

---

### Deploy API AWS

**Path**: `./cd/deploy/api/aws/action.yml`

Deploy API to AWS API Gateway

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `aws_region` | The AWS region | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `api_artifacts` |
| `api_lock` | The name of the API that should unlock | false | `` |

#### What it performs
- IAC Setup
- Create apigw directory
- Download API Artifacts
- Copy configurations
- Get cloud_type from inputs-global.yaml
- Generate release.yaml
- Generate Global Inputs global-inputs.yaml
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Migrate APIGW Terraform state
- Determine Plan Action
- Terragrunt Unlock
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Save Plan Artifacts
- Terragrunt Apply

---

### Deploy Application AWS

**Path**: `./cd/deploy/app/aws/action.yml`

Deploy Application to AWS

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `aws_region` | The AWS region | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |
| `front_end` | The front end flag, used mainly for NodeJS targets | false | `` |

#### What it performs
- IAC Setup
- Copy configurations
- Copy Values Bundle
- Create Hash value for values bundle
- Copy Values Bundle
- Generate release.yaml
- Insert release.qualifier data into release.yaml
- Insert bucket name & bucket path for beanstalk & lambda
- Generate Global Inputs global-inputs.yaml
- Generate Observability configuration for Xray
- Generate Observability configuration for datadog
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Determine Plan Action
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Save Plan Artifacts
- Restore Pipeline Artifacts
- Generate Bundle ZipFile - Upload S3
- Validate Bundle Outcome
- Terragrunt Apply

---

### Deploy Application Google Cloud Platform

**Path**: `./cd/deploy/app/gcp/action.yml`

Deploy Application to Google Cloud Platform

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `gcp_credentials` | Google Cloud Credentials | true | `` |
| `gcp_project` | Google Cloud Project Name | true | `` |
| `gcp_region` | Google Cloud Region | true | `` |
| `gcp_impersonate_sa` | Google Cloud SA Impersonation account | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `datadog` |
| `front_end` | The front end flag, used mainly for NodeJS targets | false | `` |

#### What it performs
- IAC Setup
- Copy configurations
- Copy Values Bundle
- Create Hash value for values bundle
- Copy Values Bundle
- Generate release.yaml
- Insert release.qualifier data into release.yaml
- Insert bucket name & bucket path for beanstalk & lambda
- Generate Global Inputs global-inputs.yaml
- Generate Observability configuration for datadog
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Determine Plan Action
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Save Plan Artifacts
- Restore Pipeline Artifacts
- Generate Bundle ZipFile - Upload GCP Bucket
- Validate Bundle Outcome
- Terragrunt Apply

---

### Datadog Observability deployment setup

**Path**: `./cd/deploy/app/observability/datadog/action.yml`

Datadog Observability deployment setup, process depends on target cloud

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- Datadog for HELM

---

### Datadog Observability deployment setup for HELM

**Path**: `./cd/deploy/app/observability/datadog/helm/action.yml`

Datadog Observability deployment setup for HELM chart

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- DD_TAGS
- DD_LOGS_ENABLED
- DD_APM_ENABLED
- DD_APM_NON_LOCAL_TRAFFIC
- DD_LOGS_INJECTION
- DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL
- DD_CONTAINER_EXCLUDE_LOGS
- DD_TRACE_DEBUG
- DD_DBM_PROPAGATION_MODE
- DD_DOGSTATSD_NON_LOCAL_TRAFFIC
- DD_HTTP_CLIENT_ERROR_STATUSES
- DD_HTTP_SERVER_ERROR_STATUSES
- Datadog variable Injection

---

### Xray Observability deployment setup

**Path**: `./cd/deploy/app/observability/xray/action.yml`

Xray Observability deployment setup, process depends on target cloud

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- Xray/OTEL for HELM
- Xray/OTEL for Lambdas

---

### Xray Observability deployment setup for HELM

**Path**: `./cd/deploy/app/observability/xray/helm/action.yml`

Xray Observability deployment setup for HELM chart

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- Xray variable Injection

---

### Xray Observability deployment setup for HELM

**Path**: `./cd/deploy/app/observability/xray/lambda/action.yml`

Xray Observability deployment setup for HELM chart

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- extract aws.region from inputs.yaml
- extract lambda architecture from inputs.yaml
- extract lambda runtime from inputs.yaml
- Xray/OTEL variable Injection

---

### Zip Packaging for Uploading

**Path**: `./cd/deploy/app/pack/action.yml`

Zip Packaging for Uploading

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The target cloud | true | `` |
| `cloud_type` | The target cloud type | true | `` |
| `aws_region` | The AWS region | false | `` |
| `aws_access_key_id` | AWS Access Key ID | false | `` |
| `aws_secret_access_key` | AWS Secret Access Key | false | `` |
| `aws_sts_role_arn` | AWS STS Role ARN | false | `` |
| `gcp_credentials` | Google Cloud Credentials | false | `` |
| `gcp_project` | Google Cloud Project Name | false | `` |
| `gcp_region` | Google Cloud Region | false | `` |
| `gcp_impersonate_sa` | Google Cloud SA Impersonation account | false | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `project_key` | The package name | true | `` |
| `environment` | The environment | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Bucket Config
- Stack Retrieval
- Create temp_dir
- Copy NodeJS Application Release
- Copy .env into for NodeJS
- Copy Python Application Release
- Copy .Net Application Release
- Copy Java Application Release
- Generate observability artifacts for java
- Copy Application Release
- Copy values/ into temp dir
- Generate Procfile for ElasticBeanstalk
- Generate ZIP and report filename
- Upload to AWS S3
- Upload to GCP Cloud Storage

---

### Procfile creation for ElasticBeanstalk

**Path**: `./cd/deploy/app/pack/aws/procfile/action.yml`

Create Procfile for ElasticBeanstalk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `temp_dir` | The path to the blueprint | true | `` |
| `java_stack` | The Java stack | true | `` |
| `node_stack` | The Node stack | true | `` |
| `python_stack` | The Python stack | true | `` |
| `dotnet_stack` | The .NET stack | true | `` |
| `go_stack` | The Go stack | true | `` |
| `node_apm` | The Node APM parameters | false | `` |
| `java_apm` | The Java APM parameters | false | `` |
| `python_apm` | The Python APM parameters | false | `` |
| `dotnet_apm` | The .NET APM parameters | false | `` |
| `go_apm` | The Go APM parameters | false | `` |
| `release_name` | Pass from the previous step the release name | true | `` |

#### What it performs
- Default Procfile for NodeJS
- Default Procfile for Java
- Default Procfile for Python
- Default Procfile for .Net
- Default Procfile for Go

---

### Procfile creation for ElasticBeanstalk

**Path**: `./cd/deploy/app/pack/aws/upload/action.yml`

Create Procfile for ElasticBeanstalk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `aws_region` | The AWS region | true | `` |
| `aws_access_key_id` | AWS Access Key ID | true | `` |
| `aws_secret_access_key` | AWS Secret Access Key | true | `` |
| `aws_sts_role_arn` | AWS STS Role ARN | true | `` |
| `temp_dir` | The temporary working directory | true | `` |
| `dest_zip` | The destination zip file | true | `` |
| `versions_bucket` | The S3 bucket for versions | true | `` |
| `bucket_path` | The S3 bucket path | true | `` |

#### What it performs
- Temporary STS Assume Role
- Upload to S3

---

### Bucket Config retrieval

**Path**: `./cd/deploy/app/pack/bucket-config/action.yml`

Retrieve the bucket configuration

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The target cloud | true | `` |
| `cloud_type` | The target cloud type | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- Get Bucket Name from inputs-${{ inputs.environment }}.yaml
- Get Bucket Name form release.yaml

---

### Procfile creation for ElasticBeanstalk

**Path**: `./cd/deploy/app/pack/gcp/upload/action.yml`

Create Procfile for ElasticBeanstalk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `gcp_credentials` | Google Cloud Credentials | true | `` |
| `gcp_project` | Google Cloud Project Name | true | `` |
| `gcp_region` | Google Cloud Region | true | `` |
| `gcp_impersonate_sa` | Google Cloud SA Impersonation account | true | `` |
| `temp_dir` | The temporary working directory | true | `` |
| `dest_zip` | The destination zip file | true | `` |
| `versions_bucket` | The S3 bucket for versions | true | `` |
| `bucket_path` | The S3 bucket path | true | `` |

#### What it performs
- Google Authorization
- Upload to Cloud Storage

---

### Stack Configuration retrieval

**Path**: `./cd/deploy/app/pack/stack-config/action.yml`

Retrieve the stack configuration

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The target cloud | true | `` |
| `cloud_type` | The target cloud type | true | `` |
| `environment` | The environment | true | `` |

#### What it performs
- Get Elastic Beanstalk Java  Stack from inputs-${{ inputs.environment }}.yaml
- Get Elastic Beanstalk Node Stack from inputs-${{ inputs.environment }}.yaml
- Get Elastic Beanstalk Python Stack from inputs-${{ inputs.environment }}.yaml
- Get Elastic Beanstalk .Net Stack from inputs-${{ inputs.environment }}.yaml
- Get Elastic Beanstalk Go Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda Java Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda Node Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda Python Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda .Net Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda Go Stack from inputs-${{ inputs.environment }}.yaml
- Get Lambda Rust Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine Java Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine Node Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine Python Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine .Net Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine Go Stack from inputs-${{ inputs.environment }}.yaml
- Get AppEngine Rust Stack from inputs-${{ inputs.environment }}.yaml

---

### IAC Setup Common Actions

**Path**: `./cd/deploy/common/iac/action.yml`

IAC Setup Common Actions

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `tofu_version` | The version of OpenTofu to use | false | `1.11.4` |
| `tg_version` | The version of Terragrunt to use | false | `0.98.0` |
| `tf_summarize_version` | The version of tf-summarize to use | false | `0.3.14` |
| `token` | The GitHub token | true | `` |

#### What it performs
- Terraform Plan prettifier
- Setup OpenTofu
- Setup Terragrunt v${{ inputs.tg_version }}

---

### Push Docker Image

**Path**: `./cd/deploy/container/action.yml`

Push Docker Image to registry

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `environment` | The environment to use for the build | true | `` |
| `cloud` | The target cloud | true | `` |
| `aws_region` | The AWS Region | false | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | false | `` |
| `aws_access_key_id` | The AWS Access Key ID | false | `` |
| `aws_secret_access_key` | The AWS Secret Access Key | false | `` |
| `azure_service_id` | The Azure Service ID | false | `` |
| `azure_service_secret` | The Azure Service Secret | false | `` |
| `gcp_credentials` | Google Cloud Platform credenials JSON | false | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name as key | true | `` |
| `project_owner` | The project owner | true | `` |

#### What it performs
- Download Docker Image
- Set Crane Binary
- Get Docker Registry value if set into the ENV file
- Docker Login GCP
- Docker Login Azure
- Configure AWS Credentials
- Configure AWS Credentials with Assume Role
- Docker Login AWS
- Check Docker Daemon
- Push Docker image from tar
- Push Docker image from tar using Skopeo

---

### Deploy Mobile Application AWS Device Farm

**Path**: `./cd/deploy/mobile/aws/action.yml`

Deploy Mobile Application to AWS Device Farm

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `platform_type` | The mobile platform type | true | `` |
| `aws_region` | The AWS region | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `xcode_version` | The Xcode version to use for the build | false | `` |
| `xcode_scheme` | Xcode Scheme to build and test | false | `` |
| `xcode_sdk` | Xcode SDK to build and test | false | `` |
| `xcode_destination` | Xcode Destination to build and test | false | `` |
| `android_sdk` | The Android SDK SDK to use for the build | false | `` |
| `android_destination` | The Android SDK destination to use for the build | false | `` |
| `android_configuration` | The Android SDK configuration to use for the build | false | `` |

#### What it performs
- Copy configurations
- Device Farm Name
- Device Farm Pool
- Test Script Path
- Tests Scripts Available
- Test Script Type
- Test Script Type for Schedule Run
- Generate release.yaml
- Insert release.qualifier data into release.yaml
- Generate Global Inputs global-inputs.yaml
- Determine Plan Action
- Configure AWS Credentials
- Configure AWS Credentials with Assume Role
- Device Farm ARN
- Device Pool ARN
- IOS Steps
- Android Steps
- Rename IPA/APK
- Upload IPA/APK
- Deploy Test Package
- Retrieve Device Config Filter
- Test Parameters for uploaded
- Test Parameters for Builtin FUZZ
- Schedule Run - Device Pool
- Schedule Run - Specific Devices
- Tag Run

---

### Deploy Mobile Application AWS Device Farm

**Path**: `./cd/deploy/mobile/aws/android/action.yml`

Deploy Mobile Application to AWS Device Farm

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `android_sdk` | Xcode SDK to build and test | false | `` |
| `android_destination` | Xcode Destination to build and test | true | `` |
| `android_configuration` | The Android SDK configuration to use for the build | true | `` |
| `test_script_available` | The test script availability | true | `` |
| `run_test_type` | The test script type for the run | true | `` |

#### What it performs
- Normalize Android inputs
- Restore Pipeline Artifacts
- Restore Target BuildPipeline Artifacts
- Untar extracted source_artifacts_target
- Zip test contents - Android

---

### iOS Configuration Mobile Application AWS Device Farm

**Path**: `./cd/deploy/mobile/aws/ios/action.yml`

Action to configure iOS Mobile Application AWS Device Farm release

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `xcode_scheme` | Xcode Scheme to build and test | false | `` |
| `xcode_sdk` | Xcode SDK to build and test | true | `` |
| `xcode_destination` | Xcode Destination to build and test | true | `` |
| `test_script_available` | The test script availability | true | `` |
| `run_test_type` | The test script type for the run | true | `` |

#### What it performs
- Normalize XCode inputs
- Xcode Configuration for the build
- Restore Pipeline Artifacts
- Restore Target BuildPipeline Artifacts
- Untar extracted source_artifacts_target
- Zip test contents - IOS

---

### Deploy Mobile Application Google Cloud Platform Firebase Test Lab

**Path**: `./cd/deploy/mobile/gcp/action.yml`

Deploy Mobile Application to Google Cloud Platform Firebase Test Lab

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `platform_type` | The mobile platform type | true | `` |
| `gcp_credentials` | Google Cloud Credentials | true | `` |
| `gcp_project` | Google Cloud Project Name | true | `` |
| `gcp_region` | Google Cloud Region | true | `` |
| `gcp_impersonate_sa` | Google Cloud SA Impersonation account | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `xcode_version` | The Xcode version to use for the build | false | `` |
| `xcode_scheme` | Xcode Scheme to build and test | false | `` |
| `xcode_sdk` | Xcode SDK to build and test | false | `` |
| `xcode_destination` | Xcode Destination to build and test | false | `` |
| `android_sdk` | The Android SDK SDK to use for the build | false | `` |
| `android_destination` | The Android SDK destination to use for the build | false | `` |
| `android_configuration` | The Android SDK configuration to use for the build | false | `` |

#### What it performs
- Test Script Path
- Tests Scripts Available
- Test Script Type
- Results Bucket Location
- Generate release.yaml
- Insert release.qualifier data into release.yaml
- Generate Global Inputs global-inputs.yaml
- Determine Plan Action
- GCloud Session
- IOS Steps
- Android Steps
- Rename IPA/APK
- Device configuration
- Schedule Run - Firebase Test Lab

---

### Deploy Mobile Application GCP Firebase test lab

**Path**: `./cd/deploy/mobile/gcp/android/action.yml`

Deploy Mobile Application to GCP Firebase test lab

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `android_sdk` | Xcode SDK to build and test | false | `` |
| `android_destination` | Xcode Destination to build and test | true | `` |
| `android_configuration` | The Android SDK configuration to use for the build | true | `` |
| `test_script_available` | The test script availability | true | `` |
| `test_script_path` | The test script path | true | `` |
| `run_test_type` | The test script type for the run | true | `` |

#### What it performs
- Normalize Android inputs
- Restore Pipeline Artifacts
- Restore Target BuildPipeline Artifacts
- Untar extracted source_artifacts_target
- Zip test contents - Android

---

### iOS Configuration Mobile Application gcp Device Farm

**Path**: `./cd/deploy/mobile/gcp/ios/action.yml`

Action to configure iOS Mobile Application gcp Device Farm release

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `xcode_scheme` | Xcode Scheme to build and test | false | `` |
| `xcode_sdk` | Xcode SDK to build and test | true | `` |
| `xcode_destination` | Xcode Destination to build and test | true | `` |
| `test_script_available` | The test script availability | true | `` |
| `run_test_type` | The test script type for the run | true | `` |

#### What it performs
- Normalize XCode inputs
- Xcode Configuration for the build
- Restore Pipeline Artifacts
- Restore Target BuildPipeline Artifacts
- Untar extracted source_artifacts_target
- Zip test contents - IOS

---

### Deploy Preview Application AWS

**Path**: `./cd/deploy/preview/aws/action.yml`

Deploy Preview Application AWS

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `aws_region` | The AWS region | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `container_registry` | The container registry | true | `` |
| `pull_request_name` | The pull request name | true | `` |
| `cluster_name` | The Kubernetes cluster name | true | `` |
| `rancher_project_id` | The Rancher project ID | true | `` |
| `project_owner` | The project owner | true | `` |

#### What it performs
- Get Preview Domain
- IAC Setup
- Copy configurations
- Copy Values Bundle
- Generate release.yaml
- Generate Global Inputs global-inputs.yaml
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Determine Plan Action
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Terragrunt Apply

---

### Deploy Preview Application AWS

**Path**: `./cd/deploy/preview/azure/action.yml`

Deploy Preview Application AWS

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `aws_region` | The AWS region | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `container_registry` | The container registry | true | `` |
| `pull_request_name` | The pull request name | true | `` |
| `cluster_name` | The Kubernetes cluster name | true | `` |
| `rancher_project_id` | The Rancher project ID | true | `` |
| `project_owner` | The project owner | true | `` |

#### What it performs
- Get Preview Domain
- IAC Setup
- Copy configurations
- Copy Values Bundle
- Generate release.yaml
- Generate Global Inputs global-inputs.yaml
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Determine Plan Action
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Terragrunt Apply

---

### Deploy Preview Application AWS

**Path**: `./cd/deploy/preview/gcp/action.yml`

Deploy Preview Application AWS

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `cloud_type` | The cloud type | true | `` |
| `gcp_credentials` | Google Cloud Credentials | true | `` |
| `gcp_project` | Google Cloud Project Name | true | `` |
| `gcp_region` | Google Cloud Region | true | `` |
| `gcp_impersonate_sa` | Google Cloud SA Impersonation account | true | `` |
| `aws_sts_role_arn` | The AWS STS Role ARN | true | `` |
| `aws_access_key_id` | The AWS access key ID | true | `` |
| `aws_secret_access_key` | The AWS secret access key | true | `` |
| `terraform_state_conf` | The Terraform state configuration | true | `` |
| `unlock` | Unlock the state | false | `false` |
| `lock_id` | The lock ID | false | `` |
| `destroy` | Destroy the state | false | `false` |
| `release_name` | The release name | true | `` |
| `release_version` | The release version | true | `` |
| `qualifier` | The release qualifier | false | `` |
| `project_key` | The package name | true | `` |
| `deployment_name` | The deployment name | true | `` |
| `environment` | The environment | true | `` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `container_registry` | The container registry | true | `` |
| `pull_request_name` | The pull request name | true | `` |
| `cluster_name` | The Kubernetes cluster name | true | `` |
| `rancher_project_id` | The Rancher project ID | true | `` |
| `project_owner` | The project owner | true | `` |

#### What it performs
- Get Preview Domain
- IAC Setup
- Copy configurations
- Copy Values Bundle
- Generate release.yaml
- Generate Global Inputs global-inputs.yaml
- Generate state_conf.yaml from vars.DEPLOYMENT_STATE_CONF
- Determine Plan Action
- Terragrunt Plan
- Terragrunt Plan to JSON
- TF Summarize of JSON file
- Terragrunt Apply

---

### Git-Ops Approved Command

**Path**: `./cd/gitops/approved/action.yml`

Process Git-Ops Approved Command

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `token` | The GitHub token | true | `` |

#### What it performs
- Uses: actions/github-script@v8

---

### Git-Ops Slash Commands Processing

**Path**: `./cd/gitops/command/action.yml`

Process Git-Ops Slash Commands

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `token` | The GitHub token | true | `` |

#### What it performs
- Slash Command Dispatch
- Slash Command Dispatch Pull-Request

---

### Release Workflow for Github

**Path**: `./cd/release/action.yml`

Release Workflow for Github

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `` |
| `blueprint_path` | The path to the blueprint | false | `` |
| `ref_name` | The reference name | true | `` |
| `release_tag` | The release tag | true | `` |
| `is_pre_release` | The pre-release flag | false | `false` |
| `files_globs` | The files globs to include in the release | false | `|` |
| `token` | The github token to use for the release | true | `` |

#### What it performs
- Normalize version Tag
- Get previous tag
- Changelog Generation
- Upload artifact to workflow run
- Create Release

---

### Copy APIs to blueprint

**Path**: `./cd/tasks/apis/copy/action.yml`

Copy APIs from source path to blueprint path

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `cloud` | The cloud provider to use | true | `` |

#### What it performs
- Get api_files_dir
- Get Cloud Provider
- Move Api Files

---

### JIRA Integration for Release Management

**Path**: `./cd/tasks/jira/release/action.yml`

|
  Integrates with JIRA to manage software releases by automating version tracking, issue updates, and release notes generation. 
  Synchronizes GitHub releases with JIRA versions, updates related issues status, and maintains consistency between development and project management workflows.

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `` |
| `blueprint_path` | The path to the blueprint | false | `` |
| `jira_api_user` | The JIRA API user email | true | `` |
| `jira_api_token` | The JIRA API token | true | `` |
| `atlassian_cloud_domain` | The Atlassian Cloud domain (e.g., your-domain.atlassian.net) | true | `` |
| `atlassian_cloud_id` | The Atlassian Cloud ID (e.g., your-domain.atlassian.net) | false | `` |
| `project_key` | The JIRA project key | true | `` |
| `project_id` | The JIRA project ID | true | `` |
| `token` | The github token to use for the release | true | `` |

#### What it performs
- Jira Release

---

### Check and label Pull Requests

**Path**: `./cd/tasks/repo/checkpr/action.yml`

This action checks the Pull Request and labels it

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Uses: actions/labeler@v6
- test
- Get Automatic Environment
- Get Reviewers count
- Get Reviewers list
- Assign Milestone to the PR
- Uses: actions/github-script@v8
- Uses: actions/github-script@v8

---

### Process Owners action

**Path**: `./cd/tasks/repo/owners/action.yml`

Process Owners (cloudopsworks-ci.yaml) and configure pipeline/repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `bot_user` | The bot user to use for the build | true | `` |
| `bot_email` | The bot email to use for the build | true | `` |

#### What it performs
- Retrieve branch protection rule
- Retrieve protected sources
- Check if automatic
- Reviewers Count
- Reviewers list as JSON
- Owners list as JSON
- Contributors list as JSON
- Deployments JSON
- Get repository type
- Contributor list form JSON
- Advanced Protection on GitFlow
- Advanced Deployment Environments Creation

---

### Push TAG

**Path**: `./cd/tasks/repo/push-tag/action.yml`

Push TAG into repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The GitHub token | true | `` |
| `bot_user` | The bot user | true | `` |
| `bot_email` | The bot email | true | `` |

#### What it performs
- Push TAG

---

## CI

### Patchwork action AI Agentic Patch Management Process - AutoFix

**Path**: `./ci/ai/patchwork/autofix/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `semgrep_token` | The Semgrep token | true | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |

#### What it performs
- Autofix Params
- Patchwork AutoFix
- Patchwork AutoFix - Patched-Codes

---

### Patchwork action AI Agentic Patch Management Process - DotNet

**Path**: `./ci/ai/patchwork/autofix/dotnet/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml

---

### Patchwork action AI Agentic Patch Management Process - GoLang

**Path**: `./ci/ai/patchwork/autofix/go/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml

---

### Patchwork action AI Agentic Patch Management Process - Java

**Path**: `./ci/ai/patchwork/autofix/java/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml

---

### Patchwork action AI Agentic Patch Management Process - NodeJS

**Path**: `./ci/ai/patchwork/autofix/nodejs/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml

---

### Patchwork action AI Agentic Patch Management Process - Python

**Path**: `./ci/ai/patchwork/autofix/python/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml

---

### Patchwork action AI Agentic Patch Management Process - Dependency Upgrade

**Path**: `./ci/ai/patchwork/dependency-upgrade/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |
| `libraries_io_key` | Libraries.io API Key | true | `` |

#### What it performs
- Install cdxgen
- Dependency Upgrade Params
- Dependency Upgrade Params - libraries.io
- Patchwork Dependency Upgrade
- Patchwork Dependency Upgrade - Patched Codes

---

### Patchwork action AI Agentic Patch Management Process - DotNet

**Path**: `./ci/ai/patchwork/dependency-upgrade/dotnet/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml
- Get pipeline .Net version
- Get pipeline .Net dist
- Get pipeline .Net image variant
- Get pipeline .Net build project path
- Validate project_path
- Get Package name
- Get .Net Build options
- Get .Net Build options
- Get .Net Publish options
- Get .Net Test options
- Get .Net default configuration
- Check for packages.lock.json
- Set .Net SDK
- Version SET
- Version Capture

---

### Patchwork action AI Agentic Patch Management Process - GoLang

**Path**: `./ci/ai/patchwork/dependency-upgrade/go/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml
- Check tools and install
- Get pipeline GoLang version
- Get pipeline GoLang dist
- Get pipeline GoLang arch
- Get pipeline GoLang image variant
- Get pipeline GoLang main file
- Get pipeline GoLang main file
- Get Package name
- Get Go options
- Set GoLang SDK
- Version SET
- Version Capture

---

### Patchwork action AI Agentic Patch Management Process - Java

**Path**: `./ci/ai/patchwork/dependency-upgrade/java/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml
- Get pipeline Java version
- Get pipeline Java dist
- Get pipeline Java image variant
- Get Package name
- Get Maven options
- Get Pipeline conf DependencyTrack Project type
- Set JDK
- Set up Maven
- Cache Maven packages
- Version SET
- Version Capture

---

### Patchwork action AI Agentic Patch Management Process - NodeJS

**Path**: `./ci/ai/patchwork/dependency-upgrade/nodejs/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml
- Get pipeline node version
- Get pipeline node dist
- Get pipeline NodeJS image variant
- Get package Name
- Set Node Version
- Cache NPM packages
- Version SET
- Version Capture

---

### Patchwork action AI Agentic Patch Management Process - Python

**Path**: `./ci/ai/patchwork/dependency-upgrade/python/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |

#### What it performs
- Generate  patchwork-setting.yaml
- Get pipeline Python version
- Get pipeline Python dist
- Get pipeline Python test ruff linter
- Get pipeline Python test mypy test
- Get pipeline Python image variant
- Get pipeline Python require packing dependencies
- Get pipeline Python tests tooling
- Get package Name
- Setup Python
- Install Basic Python Tools
- Version SET
- Version Capture

---

### Patchwork action AI Agentic Patch Management Process - AutoFix

**Path**: `./ci/ai/patchwork/docstrings/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |
| `base_path` | Base Path for code | false | `.` |

#### What it performs
- DocStrings Params
- Patchwork DocStrings
- Patchwork DocStrings - Patched-Codes

---

### Patchwork action AI Agentic Patch - Init

**Path**: `./ci/ai/patchwork/init/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `llm_base_url` | Local/Custom LLM implementation URL, inlcudes all OpenAI compatible API Servers | false | `` |
| `llm_model` | Local/Custom LLM implementation Model to use, e.g. gpt-4o, gpt-3.5-turbo, etc. | false | `` |
| `openai_api_key` | OpenAI API Key, required if no llm_base_url is provided | false | `` |

#### What it performs
- Free Disk Space (Ubuntu)
- Install Patchwork
- Generate patchwork-setting.yaml
- Git Tokens
- Open AI Api Keys
- Patchwork AutoFix - Custom LLM Config

---

### Patchwork action AI Agentic Patch Management Process - AutoFix

**Path**: `./ci/ai/patchwork/sonarqube/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `sonarqube_url` | The SonarQube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | SonarQube project key | true | `` |
| `project_owner` | Project Owner | false | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |
| `language` | Coding Language | true | `` |

#### What it performs
- Sonarqube Params
- Patchwork SonarQube
- Patchwork AutoFix - Patched-Codes

---

### Patchwork action AI Agentic Patch Management Process - Generate UnitTests

**Path**: `./ci/ai/patchwork/unit_tests/action.yml`

This action runs the Patchwork AI Agentic Patch Management Process

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |
| `file_extension` | Code Generation file extension | true | `` |

#### What it performs
- GenerateUnitTests Params
- Patchwork GenerateUnitTests
- Patchwork GenerateUnitTests - Patched-Codes

---

### Action to upgrade from code template

**Path**: `./ci/ai/wf-upgrade/action.yaml`

The action to upgrade from code template

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `token` | The Github token | true | `` |
| `bot_user` | The bot user to use for the build | true | `` |
| `bot_email` | The bot email to use for the build | true | `` |
| `patched_token` | Patched Code SAAS Token | true | `` |

#### What it performs
- Upgrade to latest minor version
- Push to repository
- PR Creation

---

### Save Android SDK Artifacts

**Path**: `./ci/androidsdk/artifacts/action.yml`

Save Android SDK artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `android_sdk` | Android SDK SDK to build and test | true | `` |
| `android_destination` | Android SDK Destination to build and test | true | `` |
| `android_configuration` | Android SDK Configuration to build and test | true | `` |

#### What it performs
- Normalize Android SDK inputs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Normalized Android configuration
- Upload Artifacts to workflow
- Upload Sources to workflow
- Tar Artifacts target to preserve some configurations
- Upload Target Artifacts to workflow

---

### Build Android SDK Sources

**Path**: `./ci/androidsdk/build/action.yml`

Build Android SDK sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `project_key` | The release source name, usually the repository name | true | `` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `android_version` | The Android SDK version to use for the build | true | `` |
| `android_sdk` | The Android SDK SDK to use for the build | true | `` |
| `android_configuration` | The Android SDK configuration to use for the build | true | `` |
| `android_destination` | The Android SDK destination to use for the build | true | `` |
| `android_extra_args` | The Android SDK extra arguments to use for the build | false | `` |
| `android_extra_targets` | The Android SDK extra target arguments to use for the build | false | `` |
| `android_packages` | The Android SDK packages to use for the build | false | `tools platform-tools` |

#### What it performs
- Check tools and install
- Version SET
- Version Capture
- Setup Base Java Environment
- Setup Android SDK
- Build Code
- Test Code

---

### Get Configuration Values for Android Build

**Path**: `./ci/androidsdk/config/action.yml`

Get Configuration Values for Android Build

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `environment` | The environment to use for the build | true | `` |

#### What it performs
- Android SDK list with yq
- Android Configuration for the build
- Get android_destinations from inputs-global.yaml with yq
- get and extra args from inputs-global.yaml with yq
- get android sdk extra target args from inputs-global.yaml with yq
- Get Specified Android Version
- Get Specified Android Packages

---

### Dependency Track Scan Java

**Path**: `./ci/androidsdk/scan/dtrack/action.yml`

This action scans the Java code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Xcode

**Path**: `./ci/androidsdk/scan/semgrep/action.yml`

This action scans the iOS/MacOS code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Java

**Path**: `./ci/androidsdk/scan/snyk/action.yml`

This action scans the Java code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan Android SDK

**Path**: `./ci/androidsdk/scan/sonarqube/action.yml`

This action scans the Android/Kotlin code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload Android SDK Test Artifacts

**Path**: `./ci/androidsdk/test/artifacts/action.yml`

Upload Android SDK Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Save API Artifacts

**Path**: `./ci/api/artifacts/action.yml`

Save API artifacts to the artifacts store

#### What it performs
- Get api_files_dir
- Upload ApiFiles from ${{ steps.api_files_dir.outputs.result }}/

---

### Sonarqube Scan Apis

**Path**: `./ci/api/scan/sonarqube/action.yml`

This action scans the API code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Apis Sonar Scan

---

### Retrieve Saved Target Artifacts

**Path**: `./ci/common/download/artifacts/action.yaml`

Retrieve saved target artifacts from the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to retrieve | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to retrieve | false | `source_artifacts` |
| `destination_path` | The path to the destination | false | `` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `is_tar` | The flag to extract embedded tarball from package | false | `false` |
| `exclude_opts` | The exclude options to use for the build | false | `` |

#### What it performs
- Download Target Artifacts from workflow
- Extract Tarball

---

### Install Runner tools

**Path**: `./ci/common/install/runner-tools/action.yml`

Install runner-tools for the workflow

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Platform Check with $RUNNER_OS
- Install runner-tools - Linux
- Install runner-tools - MacOS
- Install runner-tools - Windows

---

### Install Runner tools for Linux

**Path**: `./ci/common/install/runner-tools/linux/action.yml`

Install runner-tools for the workflow

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools
- Check sourcedir existence
- Get Cloud Entry
- Set Cloud Entry
- Download and Install AWS CLI
- Download and Install Azure CLI
- Download and Install GCP CLI

---

### Install Runner tools for MacOS

**Path**: `./ci/common/install/runner-tools/macos/action.yml`

Install runner-tools for the workflow

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Check sourcedir existence
- Get Cloud Entry
- Set Cloud Entry
- Download and Install GCP CLI

---

### Install Runner tools for Windows

**Path**: `./ci/common/install/runner-tools/windows/action.yml`

Install runner-tools for the workflow

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools

---

### Get Configuration Values

**Path**: `./ci/config/action.yml`

Get configuration values for the workflow from the source vars

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools
- Get owner
- Get Project Owner
- Get Environment from inputs-global.yaml for validation
- Get the deployments configuration
- Get Cloud Entry
- Get Cloud Type
- Get APIs Enabled
- Get Automatic Setting
- Set the appropriate workspace
- Check specific environment file exists
- Get Blue/Green Setting
- Set the appropriate values for REGION
- Set the appropriate values for STS Role ARN (Build)
- Set the appropriate values for STS Role ARN (Deploy)
- Set the appropriate Region for google cloud
- Set the appropriate Project for google cloud
- Set the appropriate Impersonate Service Account for google cloud (Build)
- Set the appropriate Impersonate Service Account for google cloud (Build)
- Set the appropriate values for Azure RG (Build)
- Set the appropriate values for Azure RG (Deploy)
- Set the appropriate values for Azure RG (Preview)
- Get the Runner Set for this build
- Get the Runner Set for the environment
- Get if the build is for library
- Get pipeline preview enabled
- Get deployment disabled for the environment
- Get is Automatic environment
- Get Observability Configuration
- Get Observability Agent Type
- Is JIRA Enabled?
- Get JIRA Project KEY
- Get JIRA Project ID

---

### Get Configuration Values for Terraform Modules

**Path**: `./ci/config/terraform/action.yml`

Get configuration values for the workflow from the source vars, specific for Terraform Modules

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools
- Is JIRA Enabled?
- Get JIRA Project KEY
- Get JIRA Project ID
- Get Checkov Config

---

### Get Configuration Values for Terragrunt Modules

**Path**: `./ci/config/terragrunt/action.yml`

Get configuration values for the workflow from the source vars, specific for Terragrunt Modules

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools
- Is JIRA Enabled?
- Get JIRA Project KEY
- Get JIRA Project ID

---

### Build Docker Container with BuildX

**Path**: `./ci/container/build/action.yml`

Build Docker container with BuildX

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version | true | `` |
| `docker_registry` | The docker registry | true | `` |
| `docker_image_name` | The docker image name | true | `` |
| `docker_args` | The docker build arguments | false | `` |
| `docker_inline` | The docker inline content | false | `` |
| `environment` | The environment | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `custom_usergroup` | The image variant | true | `` |
| `apm_args` | The APM arguments | false | `` |
| `front_end` | The front end flag, used mainly for NodeJS targets | false | `` |

#### What it performs
- Dockerfile Injection
- Image Variant user/group injection
- Set up Docker Buildx
- SemVer split
- Docker Image names
- Docker Build Release
- Upload Docker Image

---

### Build NodeJS Sources

**Path**: `./ci/docker/build/action.yml`

Build NodeJS sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline node version
- Get pipeline node dist
- Get package Name
- Set Node Version
- Cache NPM packages
- Version SET
- Version Capture

---

### Generate Containerized Node.js Application

**Path**: `./ci/docker/container/action.yml`

|
  This action generates a containerized Node.js application.
  It is intended to be used in a CI/CD pipeline

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `image_variant` | The image variant to use for the build | true | `` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Get pipeline image variant
- Copy Dockerfile Template Docker
- Set output with node Version
- Set custom run command
- Generalized Docker Build

---

### Semgrep code Scanning Dockerfile

**Path**: `./ci/docker/scan/semgrep/action.yml`

This action scans the Dockerfile using Semgrep and outputs the results in various formats.

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Semgrep code Scanning Dockerfile

**Path**: `./ci/docker/scan/trivy/action.yml`

This action scans the Dockerfile using Semgrep and outputs the results in various formats.

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Trivy Scan

---

### Upload Docker Test Artifacts

**Path**: `./ci/docker/test/artifacts/action.yml`

Upload Docker Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Save .Net Artifacts

**Path**: `./ci/dotnet/artifacts/action.yml`

Save .Net artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Upload Artifacts to workflow
- Upload Sources to workflow
- Upload Sources to workflow

---

### Build .Net Sources

**Path**: `./ci/dotnet/build/action.yml`

Build .NEt sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |

#### What it performs
- Check tools and install
- Get pipeline .Net version
- Get pipeline .Net dist
- Get pipeline .Net image variant
- Get pipeline .Net build project path
- Validate project_path
- Get Package name
- Get .Net Build options
- Get .Net Build options
- Get .Net Publish options
- Get .Net Test options
- Get .Net default configuration
- Get .Net default configuration
- Get Pipeline conf DependencyTrack Project type
- Check for packages.lock.json
- Set .Net SDK
- Version SET
- Version Capture
- Build Code
- Test Code
- SBOM Generation for Dtrack
- Run .Net Publishing

---

### Generate Containerized .Net Application

**Path**: `./ci/dotnet/container/action.yml`

Generate a containerized .Net application

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `dotnet_version` | The .Net version to use for the build | true | `` |
| `dotnet_dist` | The .Net distribution to use for the build | true | `` |
| `dotnet_image_variant` | The .Net image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `package_name` | The package name | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile .Net App
- Get default config_map mount point for environment
- Get xray config file from inputs-global.yaml
- Download AWS Xray agent
- Dockerfile .Net Specific Injection
- Set output with .Net Version
- Set custom run command
- Build and set startup.sh command
- Generalized Docker Build

---

### Deploy .Net Component

**Path**: `./ci/dotnet/deploy/action.yml`

Deploy .Net component to .Net repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline is_library enabled
- Register to NuGet Repo

---

### Dependency Track Scan .Net

**Path**: `./ci/dotnet/scan/dtrack/action.yml`

This action scans the .Net code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning .Net

**Path**: `./ci/dotnet/scan/semgrep/action.yml`

This action scans the .Net code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,**/bin/*,**/obj/*,PublishRelease/*,*.Tests*/**` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning .Net

**Path**: `./ci/dotnet/scan/snyk/action.yml`

This action scans the .Net code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan .Net

**Path**: `./ci/dotnet/scan/sonarqube/action.yml`

This action scans the .Net code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Install .Net Sonar Scanner
- Run Sonar Scanner .Net

---

### Upload Java Test Artifacts

**Path**: `./ci/dotnet/test/artifacts/action.yml`

Upload Java Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Save GoLang Artifacts

**Path**: `./ci/go/artifacts/action.yml`

Save GoLang artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Upload Artifacts to workflow
- Upload Sources to workflow
- Upload Sources to workflow

---

### Build GoLang Sources

**Path**: `./ci/go/build/action.yml`

Build GoLang sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Check tools and install
- Get pipeline GoLang version
- Get pipeline GoLang dist
- Get pipeline GoLang arch
- Get pipeline GoLang image variant
- Get pipeline GoLang main file
- Get pipeline GoLang main file
- Get Package name
- Get Go options
- Get Pipeline conf DependencyTrack Project type
- Set GoLang SDK
- Version SET
- Version Capture
- Build Code
- Test Code
- SBOM Download for Dtrack
- SBOM Generation for Dtrack

---

### Generate Containerized GoLang Application

**Path**: `./ci/go/container/action.yml`

Generate a containerized GoLang application

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `golang_version` | The GoLang version to use for the build | true | `` |
| `golang_dist` | The GoLang distribution to use for the build | true | `` |
| `golang_arch` | The GoLang architecture to use for the build | true | `` |
| `golang_image_variant` | The GoLang image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `package_name` | The package name | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile GoLang App
- Get default config_map mount point for environment
- Get xray config file from inputs-global.yaml
- Dockerfile GoLang Specific Injection
- Set output with GoLang Version
- Set custom run command
- Build and set startup.sh command
- Generalized Docker Build

---

### Deploy GoLang Component

**Path**: `./ci/go/deploy/action.yml`

Deploy GoLang component to Go repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline preview enabled
- Get Go options
- Deploy to Go Repo

---

### Dependency Track Scan GoLang

**Path**: `./ci/go/scan/dtrack/action.yml`

This action scans the GoLang code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning GoLang

**Path**: `./ci/go/scan/semgrep/action.yml`

This action scans the GoLang code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning GoLang

**Path**: `./ci/go/scan/snyk/action.yml`

This action scans the GoLang code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan GoLang

**Path**: `./ci/go/scan/sonarqube/action.yml`

This action scans the GoLang code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload GoLang Test Artifacts

**Path**: `./ci/go/test/artifacts/action.yml`

Upload GoLang Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Get Configuration Values for IAC repositories

**Path**: `./ci/iac/config/action.yml`

Get configuration values for the workflow from the source vars specific implementation for IAC repositories

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Install runner-tools
- Get owner
- Get the deployments configuration
- Get Automatic Setting
- Set the appropriate workspace
- Get the Runner Set for this build

---

### Save Java Artifacts

**Path**: `./ci/java/artifacts/action.yml`

Save Java artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Upload Artifacts to workflow
- Upload Sources to workflow
- Upload Target Artifacts to workflow

---

### Build Java Sources

**Path**: `./ci/java/build/action.yml`

Build Java sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Check tools and install
- Get pipeline Java version
- Get pipeline Java dist
- Get pipeline Java image variant
- Get Package name
- Get Maven options
- Get Pipeline conf DependencyTrack Project type
- Set JDK
- Set up Maven
- Cache Maven packages
- Version SET
- Version Capture
- Build Code

---

### Generate Containerized Java Application

**Path**: `./ci/java/container/action.yml`

Generate a containerized Java application

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `java_version` | The Java version to use for the build | true | `` |
| `java_dist` | The Java distribution to use for the build | true | `` |
| `java_image_variant` | The Java image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile Java App
- Get default config_map mount point for environment
- Get xray config file from inputs-global.yaml
- Download AWS Xray agent
- Dockerfile Java Specific Injection
- APM Arguments setup
- Set output with Java Version
- Set custom run command
- Generalized Docker Build

---

### Deploy Java Component

**Path**: `./ci/java/deploy/action.yml`

Deploy Java component to Maven repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline preview enabled
- Get Maven options
- Deploy to Maven Repo

---

### Dependency Track Scan Java

**Path**: `./ci/java/scan/dtrack/action.yml`

This action scans the Java code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Java

**Path**: `./ci/java/scan/semgrep/action.yml`

This action scans the Java code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Java

**Path**: `./ci/java/scan/snyk/action.yml`

This action scans the Java code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan Java

**Path**: `./ci/java/scan/sonarqube/action.yml`

This action scans the Java code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload Java Test Artifacts

**Path**: `./ci/java/test/artifacts/action.yml`

Upload Java Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Verify Java Component

**Path**: `./ci/java/test/verify/action.yml`

Verify Java component (depends on build component)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `dtrack_project_type` | The Dependency Track project type | false | `library` |

#### What it performs
- Get Maven options
- Build Code

---

### Save NodeJS Artifacts

**Path**: `./ci/nodejs/artifacts/action.yml`

Save NodeJS Artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Get pipeline zip packaging globs for TAR
- Get pipeline zip packaging exclude globs (RAW)
- Get Front-End Setting
- Get Node Build Dir
- Create TAR file
- Create TAR file for target
- Upload Artifacts to workflow
- Upload Build result
- Upload Sources to workflow
- Upload tarball of target to workflow

---

### Build NodeJS Sources

**Path**: `./ci/nodejs/build/action.yml`

Build NodeJS sources and save artifacts, requires ci/nodejs/config/action.yml

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `has_preview` | The preview flag will process only for preview builds | false | `false` |
| `install_command` | The install command | true | `` |
| `build_command` | The build command | true | `` |
| `node_extra_env` | The extra environment variables | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get pipeline owner
- Get pipeline node version
- Get pipeline node dist
- Get pipeline NodeJS image variant
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Get pipeline zip packaging exclude globs
- Get package Name
- Set Node Version
- Cache NPM packages
- Version SET
- Version Capture
- Package.JSON - REPO auto link
- Install Global Dependencies
- NPM Config Registry Setup
- Install Dependencies
- Install AWS open telemetry
- Run NPM Build
- Test Code
- SBOM Generation for Dtrack
- Remove .npmrc file

---

### Config for NodeJS Sources

**Path**: `./ci/nodejs/config/action.yml`

Configuration for NodeJS sources Requires ./bp/ci/config always be preloaded

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `environment` | The environment to use for the build | true | `` |
| `has_preview` | The preview flag will process only for preview builds | false | `false` |

#### What it performs
- Get Optional Env Vars
- Get Optional Env Vars - ${{ inputs.environment }}
- Get Optional Env Vars - ${{ inputs.environment }}
- Set Optional node_extra_env from properly calulated origin
- Get Custom Install Command
- Get Custom Install Command
- Get Node Build Dir
- Get Front-End Setting

---

### Generate Containerized Node.js Application

**Path**: `./ci/nodejs/container/action.yml`

|
  This action generates a containerized Node.js application.
  It is intended to be used in a CI/CD pipeline

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `node_version` | The Node.js version to use for the build | true | `` |
| `node_dist` | The Node.js distribution to use for the build | true | `` |
| `node_image_variant` | The Node.js image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `front_end` | The front end flag | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile Front-End App
- Get default config_map mount point for environment
- Copy Dockerfile Node.js App
- APM Arguments setup
- Set output with node Version
- Set custom run command
- Generalized Docker Build

---

### Deploy Node.js Component

**Path**: `./ci/nodejs/deploy/action.yml`

Deploy Node.js Component to NPM repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline is Library
- Get Pipeline Library destination Registry
- Get Pipeline Library Registry strategy
- Get Pipeline Library access type
- Deploy Code to Registy

---

### Dependency Track Scan

**Path**: `./ci/nodejs/scan/dtrack/action.yml`

This action scans the Node.js code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Java

**Path**: `./ci/nodejs/scan/semgrep/action.yml`

This action scans the Java code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,*/__tests__/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Java

**Path**: `./ci/nodejs/scan/snyk/action.yml`

This action scans the Java code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan NodeJS

**Path**: `./ci/nodejs/scan/sonarqube/action.yml`

This action scans the Node.js code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload NodeJS Test Artifacts

**Path**: `./ci/nodejs/test/artifacts/action.yml`

Upload NodeJS Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Verify NodeJS Component

**Path**: `./ci/nodejs/test/verify/action.yml`

Verify NodeJS component (depends on build component)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `dtrack_project_type` | The Dependency Track project type | false | `library` |
| `node_extra_env` | The extra environment variables | true | `` |

#### What it performs
- Test Code
- SBOM Generation for Dtrack

---

### Save Python Artifacts

**Path**: `./ci/python/artifacts/action.yml`

Save Python artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Upload Artifacts to workflow
- Upload Sources to workflow
- Upload Target Artifacts to workflow

---

### Build Python Sources

**Path**: `./ci/python/build/action.yml`

Build Python sources and save artifacts, requires ci/config/action.yml

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `has_preview` | The preview flag will process only for preview builds | false | `false` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |

#### What it performs
- Get pipeline Python version
- Get pipeline Python dist
- Get pipeline Python test ruff linter
- Get pipeline Python test mypy test
- Get pipeline Python image variant
- Get pipeline Python require packing dependencies
- Get pipeline Python tests tooling
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Get pipeline zip packaging exclude globs
- Get package Name
- Setup Python
- Install Basic Python Tools
- Version SET
- Version Capture
- Generate Python Environment
- Build PIP
- Build PYPENV
- Build Poetry
- Python Tests - Pytest
- Python Tests - Unittest / PyUnit
- Python Tests - Nose
- Python stubs generation
- Run Ruff Linter
- Run MyPy Test
- Install CycloneDX
- SBOM Generation for Dtrack
- Build Dependency files if they are required

---

### Build Python Sources with Basic Pip install

**Path**: `./ci/python/build/deps/pip/action.yaml`

Build Python sources with pip install

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |

#### What it performs
- Install Dependencies (PIP)

---

### Build Python Sources with Pipenv

**Path**: `./ci/python/build/deps/pipenv/action.yaml`

Build Python sources with pipenv

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |

#### What it performs
- Install pipenv
- Install Dependencies (PipEnv)

---

### Build Python Sources with Poetry

**Path**: `./ci/python/build/deps/poetry/action.yaml`

Build Python sources with poetry

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |

#### What it performs
- Install poetry
- Install Dependencies (Poetry)

---

### Build Python Sources with Basic Pip install

**Path**: `./ci/python/build/tests/nose/action.yml`

Build Python sources with pip install

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Run Python Tests

---

### Build Python Sources with Basic Pip install

**Path**: `./ci/python/build/tests/pytest/action.yml`

Build Python sources with pip install

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Run Python Tests

---

### Build Python Sources with Basic Pip install

**Path**: `./ci/python/build/tests/unittest/action.yml`

Build Python sources with pip install

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `python_extra_env` | The extra environment variables | true | `` |
| `python_requirements_file` | The requirements file | false | `./requirements.txt` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Run Python Tests

---

### Config for Python Sources

**Path**: `./ci/python/config/action.yml`

Configuration for Python sources

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `environment` | The environment to use for the build | true | `` |
| `has_preview` | The preview flag will process only for preview builds | false | `false` |

#### What it performs
- Check tools and install
- Get Optional Env Vars
- Get Optional Env Vars - ${{ inputs.environment }}
- Get Optional Env Vars - ${{ inputs.environment }}
- Set Optional python_extra_env from properly calulated origin

---

### Generate Containerized Python Application

**Path**: `./ci/python/container/action.yml`

Generate a containerized Python application

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `python_version` | The Python version to use for the build | true | `` |
| `python_dist` | The Python distribution to use for the build | true | `` |
| `python_image_variant` | The Python image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile Python App
- Dockerfile Python Specific Injection
- Set output with Python Version
- Set custom run command
- Generalized Docker Build

---

### Deploy Python Component

**Path**: `./ci/python/deploy/action.yml`

Deploy Python Component to Python repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline preview enabled
- Deploy Code to Registry

---

### Dependency Track Scan

**Path**: `./ci/python/scan/dtrack/action.yml`

This action scans the Python code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Python

**Path**: `./ci/python/scan/semgrep/action.yml`

This action scans the Python code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,*/__tests__/*,*.pyc,*.pyo` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Python

**Path**: `./ci/python/scan/snyk/action.yml`

This action scans the Python code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan Python

**Path**: `./ci/python/scan/sonarqube/action.yml`

This action scans the Python  code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload Java Test Artifacts

**Path**: `./ci/python/test/artifacts/action.yml`

Upload Java Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Save Rust Artifacts

**Path**: `./ci/rust/artifacts/action.yml`

Save Rust artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |

#### What it performs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Copy Release to bin
- Upload Artifacts to workflow
- Upload Sources to workflow
- Upload Sources to workflow

---

### Build Rust Sources

**Path**: `./ci/rust/build/action.yml`

Build Rust sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Check tools and install
- Get pipeline Rust version
- Get pipeline Rust components
- Get pipeline Rust dist
- Get pipeline Rust arch
- Get pipeline Rust image variant
- Get package name
- Get Rust Build options
- Get Rust Build options
- Get Pipeline conf DependencyTrack Project type
- Setup Rust SDK
- Install required Pipeline Cargo Components
- Install gcc toolchain
- Add Rust Target - Cross Compile
- Version SET
- Version Capture
- Test Code
- SBOM Generation for Dtrack
- Build Default Target Code
- Build Targetted Code (Cross Compile)

---

### Generate Containerized Rust Application

**Path**: `./ci/rust/container/action.yml`

Generate a containerized Rust application

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semver` | The semver version to use for the build | true | `` |
| `rust_version` | The Rust version to use for the build | true | `` |
| `rust_dist` | The Rust distribution to use for the build | true | `` |
| `rust_arch` | The Rust architecture to use for the build | true | `` |
| `rust_image_variant` | The Rust image variant to use for the build | true | `` |
| `environment` | The environment to use for the build | true | `` |
| `package_name` | The package name | true | `` |
| `is_release` | The release flag | true | `` |
| `default_registry_address` | The default registry | true | `` |
| `project_key` | The project name key | true | `` |
| `project_owner` | The project owner | true | `` |
| `observability_enabled` | The observability flag | false | `false` |
| `observability_agent` | The observability agent | false | `xray` |

#### What it performs
- Get Docker Registry value if set into the ENV file
- Get Docker Inline Setting
- Get Docker Arguments
- Get Docker Arguments for ${{ inputs.environment }}
- Get Custom Run Command
- Get Custom Usergroup
- Copy Dockerfile Rust App
- Get default config_map mount point for environment
- Get xray config file from inputs-global.yaml
- Dockerfile Rust Specific Injection
- Set output with Rust Version
- Set custom run command
- Build and set startup.sh command
- Generalized Docker Build

---

### Deploy Rust Component

**Path**: `./ci/rust/deploy/action.yml`

Deploy Rust component to Rust repository

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Get pipeline preview enabled
- Get Rust options
- Deploy to Rust Repo

---

### Dependency Track Scan Rust

**Path**: `./ci/rust/scan/dtrack/action.yml`

This action scans the Rust code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Rust

**Path**: `./ci/rust/scan/semgrep/action.yml`

This action scans the Rust code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Rust

**Path**: `./ci/rust/scan/snyk/action.yml`

This action scans the Rust code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan Rust

**Path**: `./ci/rust/scan/sonarqube/action.yml`

This action scans the Rust code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload Rust Test Artifacts

**Path**: `./ci/rust/test/artifacts/action.yml`

Upload Rust Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

### Run Checkov Scan

**Path**: `./ci/scan/checkov/action.yml`

Runs Checkov security scans on Terraform code, selecting appropriate checks based on cloud provider (AWS, GCP, Azure) and uploads scan results as artifacts and SARIF reports

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |

#### What it performs
- Determine Checkov checks
- Run Checkov
- Upload Checkov results
- Upload SARIF file

---

### Code Scan Configuration

**Path**: `./ci/scan/config/action.yml`

Code Scan Configuration

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |

#### What it performs
- Get owner
- Get Project Owner
- Get Pipeline conf Sonarqube is Enabled
- Get Fail On Quality Gate
- Get Quality Gate Enabled status
- Get Pipeline conf DependencyTrack is Enabled
- Get Pipeline conf DependencyTrack Project type
- Get Pipeline conf Snyk is Enabled
- Get Pipeline conf Semgrep is Enabled
- Get APIs Enabled
- Get the Runner Set for this build

---

### SonarQube Scan Quality Gate Status

**Path**: `./ci/scan/sonarqube/quality-gate/action.yml`

|
  This action checks the SonarQube Quality Gate status, it will fail
  if the condition is met based on the Quality Gate status.
  failure can be omitted if configured so

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |

#### What it performs
- Sonar Scan Quality Gate Status

---

### Save Xcode Artifacts

**Path**: `./ci/xcode/artifacts/action.yml`

Save Xcode artifacts to the artifacts store

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `xcode_scheme` | Xcode Scheme to build and test | true | `` |
| `xcode_sdk` | Xcode SDK to build and test | true | `` |
| `xcode_destination` | Xcode Destination to build and test | true | `` |

#### What it performs
- Normalize xcode inputs
- Get pipeline zip packaging globs
- Get pipeline zip packaging exclude globs
- Upload Artifacts to workflow
- Upload Sources to workflow
- Tar Artifacts target to preserve some configurations
- Upload Target Artifacts to workflow

---

### Build Java Sources

**Path**: `./ci/xcode/build/action.yml`

Build Java sources and save artifacts

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `artifacts_name` | The name of the artifacts to save | false | `build_artifacts` |
| `sources_artifacts_name` | The name of the sources to save | false | `source_artifacts` |
| `project_key` | The release source name, usually the repository name | true | `` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |
| `xcode_version` | The XCode version to use for the build | true | `` |
| `xcode_scheme` | The XCode scheme to use for the build | true | `` |
| `xcode_sdk` | The XCode SDK to use for the build | true | `` |
| `xcode_configuration` | The XCode configuration to use for the build | true | `` |
| `xcode_destination` | The XCode destination to use for the build | true | `` |
| `xcode_dev_team` | The XCode development team to use for the build | true | `` |
| `xcode_product_bundle` | The XCode product bundle to use for the build | true | `` |
| `xcode_extra_args` | The XCode extra arguments to use for the build | false | `` |
| `xcode_extra_targets` | The XCode extra target arguments to use for the build | false | `` |
| `xcode_unsigned` | The XCode unsigned flag to use for the build | false | `false` |
| `xcode_build_for_testing` | The XCode build for testing flag to use for the build | false | `false` |
| `build_certificate_b64` | The base64 encoded certificate to use for the build | true | `` |
| `build_certificate_pass` | The password for the certificate | true | `` |
| `build_provision_profile_b64` | The base64 encoded provision profile to use for the build | true | `` |
| `dev_build_certificate_b64` | The base64 encoded certificate to use for the build | true | `` |
| `dev_build_certificate_pass` | The password for the certificate | true | `` |
| `dev_build_provision_profile_b64` | The base64 encoded development provision profile to use for the build | true | `` |
| `keychain_password` | The keychain password to use for the build | true | `` |
| `build_export_options_plist` | The export options plist to use for the build | true | `` |

#### What it performs
- Check tools and install
- Version SET
- Version Capture
- Select XCODE version from github macos runner
- Install the Apple certificate and provisioning profile - Mobile Platforms
- Set Provissioning Profile - Xcode >= 16
- Set Provissioning Profile - Xcode < 16
- Build Code
- Get Export Options
- Generate Export Options Plist
- Export IPA - XCode Signed
- Generate IPA - Unsigned

---

### Get Configuration Values for Xcode Build

**Path**: `./ci/xcode/config/action.yml`

Get Configuration Values for Xcode Build

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `environment` | The environment to use for the build | true | `` |

#### What it performs
- Xcode Scheme list with yq
- Xcode SDK list with yq
- Xcode Configuration for the build
- Get xcode_destinations from inputs-global.yaml with yq
- Get xcode_dev_team ID from inputs-global.yaml with yq
- Get xcode product bundle ID from inputs-global.yaml with yq
- get xcode extra args from inputs-global.yaml with yq
- get xcode extra target args from inputs-global.yaml with yq
- Get Specified XCode Version
- Get Specified XCode Version
- Get if Building for Testing

---

### Dependency Track Scan Java

**Path**: `./ci/xcode/scan/dtrack/action.yml`

This action scans the Java code using Dependency Track

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `dtrack_url` | The Dependency Track URL | true | `` |
| `dtrack_token` | The Dependency Track token | true | `` |
| `dtrack_project_key` | The Dependency Track project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- SBOM Dtrack Upload

---

### Semgrep code Scanning Xcode

**Path**: `./ci/xcode/scan/semgrep/action.yml`

This action scans the iOS/MacOS code using Semgrep

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `semgrep_token` | The Semgrep token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semgrep_excludes` | The Semgrep excludes | false | `.github/workflows/*,src/test/*` |

#### What it performs
- Split semgrep_excludes
- Semgrep Code Scanning

---

### Snyk code Scanning Java

**Path**: `./ci/xcode/scan/snyk/action.yml`

This action scans the Java code using Snyk

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `snyk_token` | The Snyk token | true | `` |
| `bot_user` | The bot user | true | `` |
| `token` | The Github token | true | `` |
| `semver` | SemVer Version from build | false | `` |

#### What it performs
- Snyk Code Scanning

---

### Sonarqube Scan Xcode

**Path**: `./ci/xcode/scan/sonarqube/action.yml`

This action scans the Xcode/Swift code using Sonarqube

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `sonarqube_url` | The Sonarqube URL | true | `` |
| `sonarqube_token` | The Sonarqube token | true | `` |
| `sonarqube_project_key` | The Sonarqube project key | true | `` |
| `semver` | The Semver version | true | `` |
| `token` | The Github token | true | `` |

#### What it performs
- Get Repository Owner from inputs-global.yaml
- Get Sonnar Scanner version, if needed to be adjusted, allways defaults to latest
- Get Sonar sources form inputs-global.yaml
- Get Sonar binaries from inputs-global.yaml
- Get Sonar libraries from inputs-global.yaml
- Get Sonar tests from inputs-global.yaml (defaults to source_path)
- Get Sonar test binaries from inputs-global.yaml
- Get Sonar test inclusions from inputs-global.yaml
- Get Sonar test libraries from inputs-global.yaml
- Get Sonar extra exclusions from inputs-global.yaml
- Get Sonar exclusions from inputs-global.yaml
- Get if sonar branch setting is disabled
- Sonar Scan

---

### Upload Xcode Test Artifacts

**Path**: `./ci/xcode/test/artifacts/action.yml`

Upload Xcode Test Artifacts (depends on test/verify & build)

#### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `source_path` | The path to the source code | false | `source` |
| `blueprint_path` | The path to the blueprint | false | `bp` |
| `bot_user` | The bot user to use for the build | true | `` |
| `token` | The github token to use for the build | true | `` |

#### What it performs
- Upload Test Artifacts

---

