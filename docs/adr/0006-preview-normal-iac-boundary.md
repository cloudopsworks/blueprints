# ADR 0006: preview normal IaC boundary and current-state convergence

Status: accepted bounded amendment; central implementation and hosted/live proof remain gated.
Supersedes atomic-UID or lossless-concurrency implications in earlier preview guidance.

## Decision

Use authoritative IaC and existing normal single-writer serialization/native locks.
Selected provider namespace deletion lacks atomic expected-UID enforcement; retain
immutable UID history and fresh checks, without a raw-delete fallback. PR reopen or
privileged OOB replacement after submission is an unsupported atomic window.

Pending GitHub jobs can coalesce even with cancel-in-progress false. Every admitted
trusted route must refresh PR state and dispatch closed state to metadata-only
historical cleanup before stale artifact/head/scanner preview gates. Open/reopened
state does not authorize closure deletion. Manual exact confirmation and standing
closure policy remain distinct phases. Failures retain handles, are visible, and
need existing eligible retry; no new queue/service/knob/provider is introduced.

PR metadata planning needs deployments:read at the reusable parent ceiling, never
in source build jobs. No source deployment writes/secrets/OIDC are granted.

## Evidence boundary

This accepted operating boundary is not a runtime/hosted/live success claim.
See [detailed rollout limits](../monorepo/rollout.md#preview-operating-boundary-and-pending-run-coalescing).
