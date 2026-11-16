# ADR 0005: familiar YAML, GitFlow and authoritative IaC

Status: accepted design; runtime/provider activation remains gated.
Supersedes conflicting public configuration/provider execution details in ADRs 0001–0004.

## Context

A second JSON target tree, changed branch conventions and direct provider SDK
mutations increase migration cost and split authority from familiar Blueprints.

## Decision

Keep registry/policy in cloudopsworks-ci.yaml, environment resources in existing
vars/inputs-ENV.yaml monorepo.targets, chart values in values YAML, GitFlow defaults
and cd.deployments. Components bind IDs only. Remove external cd.targets loading.
Generated schemas/wire/native JSON are not operator configuration.

Thin familiar callers centralize actual orchestration in Blueprints. Tronador owns
source normalization and component commands; the existing exact binary installer
is used after coordinated publication. No hosted source compile or implicit latest.

Pinned Terraform/Terragrunt owns workload mutation and preview policy/probe children.
Existing parents stay external; managed child ownership is explicit and never adopts
an existing resource implicitly. Historical state receipts guard destroy/unlock.
Scanner completion precedes public publication and workload mutation.

## Consequences and verification

Adding a language component requires no workflow edits or credential duplication.
Legacy arbitrary hooks are not imported. Schema, local builds, provider plan/schema,
and hosted/live evidence remain distinct. All17 family/mode obligations remain;
unvalidated capabilities block affected delivery rather than becoming extension
points or false support claims. See the rollout runbook for current activation gaps.

## Approved bounded App Engine correction

The service-wide provider deletion effect makes version-only ownership unsafe.
The accepted correction is fresh exclusive nondefault whole-service/versions/traffic
ownership, with external application/default service/project/bucket/IAM parents.
Same-mode destroy-before-create intentionally incurs downtime; cross-standard/flex
conversion and old false-flag state adoption are not supported. True flags without
verified fresh-service history do not establish ownership. Existing operator
single-writer controls are an activation prerequisite, not a new YAML knob.
Timeout survivors/unknown operations retain historical claims and need reviewed
reconciliation, never automatic import/delete/blind retry. See the
[exact boundary and app.yaml source contract](../monorepo/rollout.md#app-engine-exclusive-service-boundary).
This accepted design amendment does not itself prove runtime enforcement or live
provider success. Generated appConfigResolved/sourceDigest are not editable config.
