---
title: "Cloud Targets"
tags: ["aws", "gcp", "azure", "deployment"]
created: 2026-11-12T20:41:21.202Z
updated: 2026-11-12T20:41:21.202Z
sources: []
links: ["release-convergence.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Cloud Targets

Seventeen target families have YAML schema examples across AWS, Google Cloud and
Azure. Schema acceptance is not provider implementation proof. Mandatory P0 must
establish exact provider/module schema, mode-specific validate/plan and actual
operation ownership/destroy behavior. Full hosting/artifact mode coverage remains
an obligation, not a completed claim; Azure Flex OneDeploy cannot be replaced by
ZIP deploy or direct SDK fallback.

Terraform/Terragrunt owns workload mutation. External parents stay external; managed
child ownership is explicit and never implicit adoption. Read-only verification and
registry publication have separate scopes. See [current rollout](../docs/monorepo/rollout.md)
and [[rollout-verification]].

App Engine's approved scope is fresh exclusive nondefault whole-service/versions/
traffic. Replacements intentionally recreate the service with downtime; no old
false-state adoption or standard↔flex update. Application/default service/project/
bucket/IAM stay external. Existing operator single-writer control is required;
unknown timeout survivors retain historical claims and need reviewed reconciliation,
not auto-import/delete/blind retry. app.yaml exact bytes produce generated projection;
entrypoint is explicit or existing iac.entrypoint fallback. Gen2 eventSource derives
from existing probes. Azure runtime versions are explicit; production/slot claims
are hierarchical, APIM owns whole API identity, public Azure endpoints only.
See [current detailed boundary](../docs/monorepo/rollout.md#app-engine-exclusive-service-boundary).

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
