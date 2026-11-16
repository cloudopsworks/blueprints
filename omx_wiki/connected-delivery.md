---
title: "Connected Delivery"
tags: ["monorepo", "delivery", "scanning", "recovery"]
created: 2026-11-13T19:33:06.108Z
updated: 2026-11-13T19:33:06.108Z
sources: []
links: ["monorepo-architecture.md", "release-convergence.md", "rollout-verification.md", "kubernetes-previews.md"]
category: pattern
confidence: medium
schemaVersion: 1
---

# Connected Delivery

## Accepted design

Keep the existing branch, version-tag and PR habits. CI produces one repository
version and builds changed components. One automatic native `workflow_run` delivery
continuation follows the existing main/eligible merged-closure CI entrypoints;
the origin does not wait for it. Existing PR preview routing remains separate.

Delivery authenticates the exact origin attempt and retains both the real planner's
computed-plan/upload-readback proof and a separate source-free origin proof.
Captured protected-base policy survives merged-closure routing; today's default
branch or PR/base tip cannot replace that original authority. Cleanup remains an
independent closure outcome, not a prerequisite that disguises CI failure.

Every current component receives all five scanner outcomes, including unchanged
components carrying older verified builds. Original source SHA, build version and
payload digest remain original; current policy controls scan requirements and
deployment eligibility. The fresh required barrier precedes eligible tag creation,
the complete final stage, deployment and release. Uploaded, processing, unavailable
or missing required results are not a passed gate.

Source builds/scanners have no cloud/OIDC/deployment authority. Privileged jobs
consume authenticated data and reuse Blueprint composites. No GitHub event spoof,
dispatcher, polling scheduler, Python helper engine or replacement control plane is
part of this decision.

## What changes for developers

- Follow the same familiar triggers and one repository version; no per-component
  workflow edits are required by the accepted model.
- Read the linked CI origin and delivery outcomes. Attempt-specific Checks provide
  visibility, not a constant latest-origin branch-protection guarantee. Historical
  green records may remain; cancelled work can retain a non-success pending record.
- Keep `/retry` for PR automerge retry. To recover delivery, use GitHub **Re-run all jobs**
  on the linked originating CI run. This creates fresh mandatory proofs and builds.
  Failed-jobs-only/specific-job reruns retaining earlier proofs are not accepted;
  rerunning the continuation cannot recycle finalized ownership.
- Continue editing YAML under `.cloudopsworks/`. Do not configure check IDs,
  publication receipts or JSON orchestration settings. State/backend configuration
  still comes from organization/team `DEPLOYMENT_STATE_CONF`, not application files.

## Implementation status

The design is accepted; central workflow implementation is in progress. Reviewed
input-authentication work is a prerequisite, not complete normal delivery. Normal
incremental baseline/final-stage admission remains gated until the real current-
policy all-component barrier and complete normal producer are verified. Do not
infer full lifecycle success from a narrow input or renderer test.

The full seven-language/Ruby/Rails scope, all 17 deployment families/47 native modes
across AWS/Azure/GCP, Kubernetes previews, slash commands, owners, registry,
destroy/unlock, documentation and QA remain required. Terraform/Terragrunt and
`kubernetes/helm/charts` remain authoritative. Previews use one shared namespace
per PR/target, with component-specific workloads.

## Activation and verification

The continuation must exist on the default branch with coordinated released
Blueprint/CLI pins. Catalog activation remains blocked pending actual execution
and separately authorized hosted/provider checks. This page reports accepted
requirements, not successful hosted deployments or live cloud verification.

Verify actual event routing, original-source scans, carried provenance, fresh
required failures, all-jobs recovery and cancellation presentation in the hosted
canary before activation. Local checks cannot exercise the GitHub UI recovery path.
Keep local/native, hosted and live-provider evidence separate.

See [ADR 0008](../docs/adr/0008-native-scan-delivery-continuation.md),
[[release-convergence]], [[rollout-verification]] and [[kubernetes-previews]].
