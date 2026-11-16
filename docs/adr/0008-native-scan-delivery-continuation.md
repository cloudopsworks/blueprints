# ADR 0008: native scan host and connected delivery

Status: **Accepted design**; implementation and activation verification remain pending.
Supersedes earlier main/merged-closure host and scan-before-stage ordering details,
not their branch/tag triggers or operational requirements.

## Context

Changed components build once under one repository version. Unchanged components
can carry verified artifacts from older builds. Configured scanners must inspect
each component's original source under the current policy without relabelling its
source SHA, build version or artifact digest.

Native Semgrep CI push/PR metadata can select the event's commit instead of a
carried component's checkout. Overriding GitHub metadata or checking only the final
HEAD would not prove which source was scanned.

## Decision

Keep the familiar develop/support/release, version-tag and PR entrypoints. Origin
CI plans and builds; **one real `workflow_run` continuation** then owns the common
main/eligible merged-closure delivery graph. Origin CI finishes without waiting on
its continuation. Cleanup remains independent in the original closure route.

The accepted ordering is:

1. Verify history and source trust before freezing the plan; materialize legitimate
   unavailable history before selection, not after the plan is frozen.
2. Retain the same-job computed-plan/upload-readback endorsement. A separate
   source-free origin writer verifies that edge and preserves exact event facts.
3. Authenticate selected and carried original build plans, results and payloads.
   Run all five scanner outcomes for every current component under current policy.
4. Require the fresh current-attempt scan barrier before any eligible frozen-tag
   creation, complete final stage, deployment or release.
5. Reuse the complete stage for the authoritative deployment/release lifecycle.

For merged closure, retain the original captured protected-base policy alongside
the merge source. Do not reconstruct it from today's PR/base tip. Intersect the
applicable operation/target grants; stricter required scans cannot be disabled by
older artifact settings. Source/scanner jobs receive no cloud credentials, OIDC or
deployment writes. Privileged assembly consumes verified data, not source scripts.

Use native non-push/non-PR scanner hosts and supported original source metadata;
never rewrite `GITHUB_*` or event contents. Reuse named Blueprint composites and
the released Tronador installer, not Python or another helper orchestration engine.
There is no dispatcher, polling loop, waiting origin holder or watchdog.

## Visibility and recovery

Attempt-specific Checks link delivery outcomes to the original source and CI
attempt. Exact identity and ownership are required; these checks are visibility,
not deployment authority or a constant latest-origin branch-protection context.
Older green records may remain visible, and cancellation may leave a non-success
queued/in-progress record. Do not promise an unconditional finalizer.

`/retry` remains PR automerge retry. Delivery recovery uses GitHub **Re-run all jobs**
on the linked originating CI run, producing fresh initializer, planner, proof and
build jobs. Partial reruns that retain mandatory earlier-attempt outputs are not
accepted. A direct continuation rerun cannot recycle a finalized check.

## Implementation and Activation boundaries

Implementation is in progress. The reviewed input-authentication slice does not
activate normal incremental baselines or final stages. Those paths remain gated
until the real all-component scan barrier and complete normal stage producer are
implemented and independently verified. Estimates do not prove budget fit.

Activation additionally requires the thin continuation on the default branch,
coordinated released Blueprint/CLI pins and a separately authorized hosted canary.
Local typed/native tests are not hosted event, credential or live-provider proof.
Module-catalog activation remains blocked.

All seven languages, Ruby/Rails, AWS/Azure/GCP deployment families and native modes,
Kubernetes previews, slash commands, owners, registry, destroy/unlock, documentation
and QA remain required. YAML `.cloudopsworks/` configuration, organization/team
`DEPLOYMENT_STATE_CONF`, authoritative Terraform/Terragrunt and the authoritative
Helm charts remain unchanged. Users configure no check IDs, receipt files or new
JSON control plane.

See the [connected delivery wiki](../../omx_wiki/connected-delivery.md) and
[rollout evidence boundaries](../monorepo/rollout.md#evidence-levels).
