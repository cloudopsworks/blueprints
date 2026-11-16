# Rollout, ownership and verification

## Current activation gate

CLI v0.6.0 and Blueprints immutable v5.11.0/floating v5.11 are coordinated,
unpublished rollout prerequisites. Hosted jobs must install the exact released
binary using `cloudopsworks/install-tronador-cli@v1`; never compile CLI source or
select latest in hosted jobs. Source-built `/tmp/tronador-v511-revision` is local
implementation evidence only. Thin callers now implement the frozen interface fixture. Central execution and
mandatory provider P0 capability verification remain in progress: do not claim full
CI/CD/provider completion from caller/schema validation.

Seventeen YAML examples describe schema-supported target families, **not seventeen
proved provider implementations**. Each hosting/artifact mode requires selected
module/provider revision, provider schema, validate/plan, actual operation-path and
ownership/destroy proof. Azure Functions Flex OneDeploy and package access require
separate capability evidence; ZIP deploy is not a substitute. Any failed capability
remains a bounded blocker, never an SDK fallback or silently dropped mode.

## Resource ownership and operations

Workload mutations belong to authoritative pinned Terraform/Terragrunt operations,
not direct SDK mutation. `blueprints/kubernetes/helm/charts` is authoritative for
normal and preview workloads; there is no copied chart fork. Registry publication
and read-only identity/readiness probes have separate scopes.

Targets default to `ownership: external`. No implicit adoption/import occurs.
Explicit `managed` child ownership requires verified fresh creation or already-owned
state; shared clusters, namespaces/groups, hosting plans and other parents remain
external unless their separately reviewed owned-child contract says otherwise.
Do not treat changing this field as permission to take over an existing workload.

Preview stays Kubernetes-only: one PR/target grouping and shared namespace with
component-specific releases. Namespace/policy/canary/probe children are IaC-owned;
verification must not create persistent resources. Actual admission/CNI isolation,
readiness and safe owned-child cleanup are activation checks, not mocked success.

Destroy/unlock must use a verified historical nonsecret StateHandle, persisted and
read back before backend INIT. Native backend addresses/workspaces/lock IDs are
not GitHub concurrency names. Removed components or changed YAML must not redirect
recovery to current state. Never export raw plans, state, generated IaC trees,
provider diagnostics or secret-bearing inputs; apply uses a saved plan in the same
protected workspace. Recovery is internal to validated receipts, not operator JSON.

## Protected GitHub settings

Use canonical protected environment names matching actual owners and privileged
jobs (for example `develop/dev`, `release/prod`, support and preview classifications).
Cloud/state environment is distinct. Protect default branches and OIDC subjects.

The operator maps below are bounded YAML, not public application credentials:

| Setting | Purpose |
|---|---|
| CLOUDOPSWORKS_AUTH | authRef to AWS/GCP/Azure federation binding |
| CLOUDOPSWORKS_IDENTITIES | authRef to expected account/project/subscription |
| CLOUDOPSWORKS_REGISTRIES | authRef to native provider/repository destination |
| CLOUDOPSWORKS_PROBE_SECRETS | protected secretRef values for authenticated probes |
| CLOUDOPSWORKS_HOST_KEYS | protected exact Azure app/slot administrative key records |

Inactive `examples/protected/` files show the YAML shapes. Never commit real secret
values. Normalize maps with stdin only, for example:

```sh
tronador components settings --kind auth --json < operator-auth.yaml
```

Do not add an operator publication-store variable, workflow hash, or handwritten
receipt. Artifact locators, wire JSON, native manifests and schemas are generated
machine contracts, not another public configuration model.

## Scanner and publication gate

The required scan barrier must finish before public release publication or workload/
preview mutation, including carried/config-only convergence. Advisory, findings,
error, unsupported, pending and upload-processing states are distinct; a successful
upload is not a completed scan. Forks do not gain protected credentials. Required
failures produce zero downstream mutation. Runtime implementation/hosted evidence
must establish these properties before activation.

## Evidence levels

1. CLI schema/corpus/golden validation proves source normalization and wire shape.
2. Local temporary-copy language builds/tests prove actual source execution.
3. Provider-schema/plan fixtures prove only the selected module/resource mode.
4. Hosted Actions, cloud mutation/readiness, registry promotion and live CNI/cleanup
   require their own authorized executions. They are not proved by local mocks.

Local Docker absence prevents actual OCI/preview package proof. Cloud credentials,
live Kubernetes and hosted execution are not supplied. No release/tag/push/cloud
operation is authorized by a branch, plan review or local source-built CLI.

## GitOps/protection setup and exact hosted names

Populate real `config.owners`/`config.reviewers` admin identities before activation;
templates intentionally contain empty lists rather than fictional users. Component
protection requires `branchProtection: true`, `requiredReviewers >= 1`, a protected
master/main/develop policy source, and broad protectedSources `.github/**` **and**
`.cloudopsworks/**`. Public-repository source PUSH protections are unsupported in
component mode and fail explicitly; legacy defaults remain unchanged.

`BOT_TOKEN` must be a supported bot **user PAT/OAuth** credential with the reviewed
repository/admin capability; an installation-only token cannot satisfy `/user`.
`BOT_TOKEN_SCOPED` is the separate read-only policy snapshot reader. Keep both in
protected GitHub secrets, never application YAML. Existing incompatible protection
records or overlapping unmanaged patterns need explicit operator migration before
writes. Stronger/equal protections are retained, not silently deleted/replaced.

The reviewed reusable graph predicts required status
`checkpr / Check Pull Request`, while legacy remains `Check Pull Request`. Verify
the exact hosted check-runs API result before activating protection. Publisher
names are likewise reviewed graph contracts, not hosted API evidence:

- main: `lifecycle / monorepo-stage-publisher`
- PR: `ci / monorepo-stage-publisher`
- close: `close / lifecycle / monorepo-stage-publisher`

Successful publisher job/attempt and canonical trusted caller/event provenance
must be verified. Matching a suffix, another reusable hop, an uploaded artifact or
an aggregate job name is not sufficient authority. No extra caller nesting is
permitted without updating the reviewed fixture and downstream verifier together.

## App Engine exclusive-service boundary

The approved lifecycle boundary is a **fresh, component-exclusive nondefault
service**, including its versions and traffic—not ownership of a single version.
The application, default service, project, artifact bucket, IAM and service identities
remain external. Canonical ownership is resolved project/application plus service;
changing region, auth alias, component ID or backend key does not create a new owner.

Explicit managed creation and verified exclusive-service history are prerequisites.
Existing unowned services, old false/missing `delete_service_on_destroy` states,
missing history and a merely matching name/digest cannot be silently adopted.
Setting a true flag alone does not establish ownership. Separately reviewed operator
reconciliation is required; there is no automatic import or flag-only migration.

Same-mode replacement deliberately deletes/recreates the whole owned service
before creating the new version and traffic. **Downtime is intentional.**
Create-before-destroy and in-place standard↔flexible transitions are outside the
contract. Standard ZIP, flexible-native ZIP and flexible OCI are independent initial
modes, not a promise of cross-mode conversion. Destroy excludes all shared parents.

Before activation, existing operator permissions/processes must establish one
writer for this service. Repository-local serialization/inventory cannot exclude
an arbitrary external repository or out-of-band writer. Denied/incomplete inventory,
foreign versions/traffic and unestablished exclusivity block safe operation; no new
public configuration field or coordinator is introduced by this prerequisite.

Timeouts can leave pending deletion or a live version whose provider state ID was
cleared. Retain the historical claim/handle. Unknown operations, orphan versions or
live/state discrepancies require reviewed reconciliation—not auto-import, blind
retry, automatic deletion or stale-plan replay. Recovery uses the same verified
historical identity and a fresh saved plan only after resolved operation/absence
checks. Release claims only after authoritative completion and service absence.
Exact version/artifact, traffic and HTTP readiness are separate success conditions.
Provider source/offline plans and local protocol tests do not prove live recovery.

### Existing app.yaml, not a second configuration model

`appConfig` points to an existing root-relative safe YAML/YML file. Tronador strictly
parses a closed selection of service/runtime/environment, explicit entrypoint,
instance/runtime configuration and scaling fields, binding the **exact source bytes**
with `sourceDigest`. Unknown/duplicate/multi-document fields fail; arbitrary YAML
extensions and environment-variable payloads are not accepted as privileged inputs.
The wire `appConfigResolved` and typed operation `appConfig` are generated data:
never author them in environment YAML or invent their digest.

Standard native mode requires an explicit command in app.yaml or the existing
`iac.entrypoint` fallback; conflicting commands fail and none is guessed. The
inactive standard example uses `python app.py`, matching the Python scaffold;
the prepared ZIP must actually contain that application. Flexible native adds an
explicit runtime_config; flexible OCI uses `env: flex`, `runtime: custom`, and the
immutable image's entrypoint. The three source examples are under
`.cloudopsworks/examples/appengine/`; they are shape/normalization examples, not
live deployment proof or automatic mode migration.

## Gen2 and Azure source boundaries

Gen2 event-source operation data is derived from existing `trigger` and readiness
probe source/resource fields, validated for agreement and stripped of probe bodies.
Do not add a human `eventSource` field. HTTP mode does not invent an event source.

Azure ZIP examples declare the actual runtime grammar: App Service
`runtime: PYTHON|3.13`; Functions `workerRuntime: python` plus `runtime: '3.13'`.
Versions are explicit, never inferred from the worker name. Existing plan/identity/
package-storage parent IDs stay in their typed `iac` fields; package-read SAS stays
in protected auth, never vars examples. Production app ownership conflicts with
child-slot ownership; distinct exact slots can be independent under hierarchical
claims. APIM owns the whole API identity, not an exclusive revision, so revisions
cannot be used to partition ownership. Current Azure endpoint validation covers
public Azure endpoints only; sovereign/custom endpoint support is not claimed.
These contracts and examples do not establish hosted/live provider readiness.

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
