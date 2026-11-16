# Tronador component commands and boundaries

Tronador owns schema, bounded YAML parsing, lifecycle classification, scaffolds,
affected selection, exact toolchain closure and typed build/test/package. Blueprints
owns central orchestration, verified artifact transport, scans, authorization and
Terraform/Terragrunt operation execution. No second YAML resolver or arbitrary
shell/module path is permitted under deployment credentials.

Commands implemented in the revision source:

- `components validate/list/schema/capabilities`: inspect the closed source contract.
- `components lifecycle --event EVENT --ref REF --base-ref BASE --json`: normalized
  familiar branch/tag classification; legacy extracted mapping compatibility uses
  `--deployments-stdin --compat legacy` without requiring a component registry.
- `components plan`: shared-version, affected/closure and target selection as data.
- `components add ID --language LANGUAGE [--framework rails]`: atomic, collision-safe
  generation, empty target bindings, preserved unrelated labeler rules/comments.
- `components new PATH --language ruby [--framework rails]`: runnable standalone
  plain Ruby or Rails, never overwrites an existing repository.
- `components build/test`: real native commands, exact preflighted tools; no secrets.
- `components package --plan FILE`: plan-bound package output; Docker required for
  default OCI and preview projections; missing tools never count as successful work.
- `components settings --kind KIND --json`: strict bounded protected YAML on stdin.
  Internal `--kind backend` is the sole Go pre-auth BackendSettings projection of
  existing native YAML; it acquires no credentials and adds no operator concept.
  Protected map kinds remain auth/identities/registries/probe-secrets/host-keys.
- `components operations`: closed nonsecret data for authoritative pinned IaC, not
  permission for direct SDK workload mutation or proof of every provider capability.

Use `--help` for exact flags. JSON outputs are generated machine wire contracts;
editable registry/environment/settings configuration stays YAML. Mirrors under the
templates' schemas directory are copied byte-for-byte from CLI authority. Update
mirrors only after coordinating the source schema, corpus and operation goldens.

README.yaml is maintained source; `tronador readme build` generates README.md.
No Makefile is added. The unrelated Go-template `_VERSION` marker is not the CLI
software version. The exact CLI release must exist before hosted installation;
local source builds do not replace publication and activation gates.

## Existing GCP configuration projection

App Engine app.yaml is strictly parsed from exact source bytes into generated
appConfigResolved, then typed operation appConfig; sourceDigest is derived, not
human authored. Standard entrypoint is explicit in app.yaml or existing iac.entrypoint,
never guessed. Flexible native and custom OCI retain their separate closed runtime
shapes. Gen2 eventSource derives only from existing trigger/readiness source/resource
and omits probe bodies; HTTP has no synthetic event source. No developer knob was
added. See the [ownership/recovery runbook](rollout.md#app-engine-exclusive-service-boundary).

## Existing scanner configuration compatibility

The sole CLI resolver projects eleven existing scanner fields into generated
`resolved.scanners`, including distinct application `semgrepEnabled` and Terraform
`terraformSemgrepEnabled`. Human settings remain the existing YAML locations:
`.cloudopsworks/vars/inputs-global.yaml` for application scanner sections and
`.cloudopsworks/inputs.yaml` for Terraform `checkov`, `secret_scan`, `semgrep`.
Do not add a required-scanner human field or author resolved wire JSON. Applicability,
credentials and required gate policy are separate trusted decisions.

Legacy yq boolean quirks are intentionally preserved, not normalized away:

- Default-false/`and true` fields (`enabled` for application scanners and
  `sonarqube.fail_on_quality_gate`) treat both quoted `"true"` and `"false"` as truthy.
  Use YAML boolean `false`, not quoted `"false"`, to disable those fields.
- Default-true/`// "true"` fields (`sonarqube.quality_gate_enabled`, Terraform
  `checkov.enabled`, `secret_scan.enabled`, `semgrep.enabled`) substitute true for
  missing **or boolean false**. Quoted `"false"` disables these fields; quoted
  `"true"` enables them. Boolean false does not disable these default-true fields.
- `dependencyTrack.type` retains its existing Application fallback for missing/
  boolean-false input; this is a project-type string, not another boolean flag.

The typed projection preserves compatibility; it does not itself establish scan
completion, supported-provider coverage or hosted gate execution.

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
