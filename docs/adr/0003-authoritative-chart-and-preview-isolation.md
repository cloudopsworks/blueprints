# ADR 0003: Authoritative Helm chart and isolated PR groups

> Historical initial design. Conflicting configuration/execution claims are superseded by [ADR 0005](0005-yaml-gitflow-iac-revision.md); not current provider capability proof.

- Status: accepted; includes the explicit authoritative-chart requirement

## Decision

`kubernetes/helm/charts` is the authoritative chart for both normal Kubernetes
applications and previews. Opt-in `monorepo.enabled` values select the fixed,
hardened workload. Do not copy it into a separate application or sandbox chart.
Legacy default rendering is regression-tested byte for byte. Chart metadata stays
at `5.10.0` in this change; the Blueprint platform version is independently `v5.11.0`.

Previews run only on EKS, GKE and AKS. Each repository/PR/target has one
deterministically named owned namespace, with separate component Helm releases.
A component failure retains the namespace and successful siblings for retry.

The privileged workflow verifies repository, originating workflow ID, successful
run/attempt, PR number and current head. Forks, stale heads, closed PRs and corrupt
or mismatched data-only artifacts are denied. Targets, federation bindings, chart
and isolation policy come from trusted configuration, not PR artifacts. No PR
script, chart, hook or source checkout runs in this privileged path.

Before PR pods run, restricted admission and an enforcing CNI are prerequisites.
Actual paired control/denial, provider metadata, DNS and intended-ingress probes
must establish isolation. A NetworkPolicy document or ready daemon alone is not
proof. Workloads have no service-account token by default, restricted security
contexts, bounded resources and a read-only application filesystem.

Deployment and close cleanup share a concurrency identity. Cleanup rechecks PR
state and namespace ownership and uses UID/resourceVersion deletion preconditions;
it never deletes wildcard namespaces or adopts foreign ones.

## Consequences

First previews need materialized images for all active components. The read-only
CI planning job can use trusted prior PR state as its baseline. Missing,
inconsistent or non-ancestor state selects all; later continuous PR updates build
only affected components. This does not grant cloud credentials to source builds.

See [preview prerequisites](../monorepo/rollout.md#kubernetes-preview-prerequisites).
