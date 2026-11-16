---
title: "Kubernetes Previews"
tags: ["preview", "kubernetes", "security"]
created: 2026-11-12T20:41:20.847Z
updated: 2026-11-12T20:58:50.438Z
sources: []
links: ["release-convergence.md", "rollout-verification.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Kubernetes Previews

Previews remain Kubernetes-only, one PR/target namespace with component-specific
releases. Authoritative charts live in kubernetes/helm/charts, not template forks.
IaC owns namespace/policy/probe/canary children; read-only verifier does not leave
persistent writes. Privileged paths never execute PR source/charts/hooks.

Actual admission/CNI enforcement, intended-build readiness and owned-child cleanup
require live proof. Current local tests do not supply that proof. Hosted caller activation remains gated. See [rollout](../docs/monorepo/rollout.md) and
[[cloud-targets]].

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
