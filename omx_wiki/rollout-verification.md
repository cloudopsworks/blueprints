---
title: "Rollout Verification"
tags: ["rollout", "verification", "compatibility"]
created: 2026-11-12T20:41:21.375Z
updated: 2026-11-12T20:41:21.375Z
sources: []
links: ["monorepo-architecture.md", "kubernetes-previews.md", "cloud-targets.md"]
category: environment
confidence: medium
schemaVersion: 1
---

# Rollout Verification

CLI v0.6.0 and Blueprints v5.11.0/v5.11 are unpublished coordinated prerequisites.
Hosted jobs must use the existing exact-pinned binary installer, not source builds
or latest. Thin interfaces are frozen; provider P0 and hosted activation remain gated.

Keep four proof levels distinct: schema/goldens, actual local source builds/tests,
provider schema/plan/operation fixtures, and authorized hosted/live deployment/CNI.
Docker is absent locally; no OCI success, hosted Actions or cloud mutation is claimed.

Temporary-copy smokes are tests/monorepo/smoke_templates.py and smoke_migration.py.
The latter uses actual Go reference source and preserves deployment/GitFlow/version
and workflow hashes across four language additions. It is not a legacy-hook importer.
See [runbook](../docs/monorepo/rollout.md), [[monorepo-architecture]] and [[cloud-targets]].

## Preview operating boundary and pending-run coalescing

The approved boundary is the normal single-writer, authoritative IaC lifecycle
used by language templates—not an atomic GitHub/Kubernetes transaction. The selected
namespace provider does **not** issue atomic expected-UID conditional deletion.
Immutable recorded namespace UID remains generation evidence; fresh PR/namespace/
ownership checks and historical claims must be retained. Do not refresh history to
match a replacement. No raw kubectl/SDK delete fallback is permitted.

All conforming PR/target namespace/component/probe writes require the same verified
serialization group and native state locks. This does not atomically exclude a
privileged out-of-band replacement or PR reopen after apply submission. Detected
changes stop later mutation; uncertain submitted operations retain historical
handles for reviewed recovery. Normal external replacement/adoption is unsupported.
No new provider, coordinator, public knob or atomic-race guarantee is introduced.

GitHub `cancel-in-progress: false` preserves a running job but is **not a lossless
queue**: a newer pending job can replace a pending closure job. After trusted route
admission, fetch current PR state. The required convergence contract routes a now-
closed PR into metadata-only historical cleanup **before** stale build-head,
artifact availability or scanner preview-eligibility gates. Thus a newer eligible
route can replace a pending close without ignoring current closure. An open/reopened
PR performs no closure deletion; wrong callers remain denied.

Standing closure-policy cleanup is a distinct authorization phase/outcome, not an
expansion of a manual destroy/unlock confirmation. Manual operations remain exact;
only an exactly confirmed native lock may be unlocked. Cleanup failure is visible,
keeps historical claims/handles and forbids later rollout. There is no eventual-
delivery guarantee after runner/API/provider failure without an existing eligible
trigger or explicit retry. Existing commands can retry the authorized operation;
no new scheduler/trigger is promised.

These are approved implementation requirements. Central convergence/cleanup tests
and hosted/live provider/CNI verification remain separate gates; documentation and
local caller checks are not evidence that those gates have completed.

The PR caller and nested parent permission ceilings now include `deployments: read`
for the metadata-only affected-plan baseline. Source build jobs do not gain this
read permission, deployment writes, secrets or OIDC from the caller ceiling.

## Independent workload and backend authentication

The approved backend-auth amendment reuses the existing `auth_ref` field in native
S3, GCS and Azure backend YAML and the **same** protected CLOUDOPSWORKS_AUTH map.
Target `authRef` selects workload credentials; backend `auth_ref` independently
selects state/lock credentials, including cross-cloud or same-provider distinct
principals. No new top-level secret/map, CLI flag, credential broker or ordinary
component-add setup is introduced. Platform operators configure existing bindings;
adding another component still requires no new credentials.

Fresh generated handles/context must freeze a separate backendIdentity (AWS account,
GCP configured projectNumber, or Azure tenant/subscription), alongside unchanged
workload providerIdentity and the exact selected alias union. This is generated
machine evidence, never a human field. Backend credential identity proves selected
principal/context, **not ownership of a globally named bucket/storage account**.
Explicit backend address and historical authorization still govern access.

Only selected aliases may be acquired, with private independently captured contexts.
A later login must not replace the earlier context. Native backend init/state/lock/
private-state readers use the backend context; workload deployment/registry/readiness
uses the workload context. Native credential precedence/fallback isolation requires
selected-binary tests; planning/source/schema evidence is not proof of that routing.

Old handle bytes/digests are not eagerly rewritten. Legacy implicit S3/GCS works
only with matching backend/workload cloud and the **same selected workload principal
and identity**. Legacy Azure triple refs must resolve to one unambiguous workload
binding, verified current tenant/client and unchanged historical subscription.
Old handles did **not** freeze tenant; do not retroactively claim they did. Distinct
backend principals, cross-cloud state or ambiguous legacy identity are not inferred;
unprovable recovery fails closed and requires separately reviewed migration.

Current AUTH binding rotation may retain the verified frozen canonical context;
changing AWS account, configured GCP project, Azure tenant/subscription is forbidden
identity retargeting. Changing/removing current YAML cannot redirect historical
backend address or auth selection. Expired/denied credentials fail closed; an
uncertain apply is not blindly replayed under a fresh login.

Temporary backend credentials can persist in native `.terraform` metadata, saved
plans and caches. **The entire private execution/backend/plan/native-cache tree is
secret-bearing and must never be exported**—not just selected token files. Private
directories/files require restrictive modes, same protected execution lifetime,
no secret argv/debug output and no raw diagnostic uploads. Receipts/handles contain
only reviewed nonsecret identity/address evidence, never tokens or credential paths.

This is an approved implementation contract. CLI/auth/native integration and
backward-compatibility verification remain pending while interfaces freeze;
hosted OIDC/native access/live provider proof is a separate activation gap. No
cross-cloud or same-provider credential-routing success is claimed by these docs.
