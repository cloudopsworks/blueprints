# Monorepo applications — v5.11 revision

This opt-in model keeps Blueprints as the CI/CD platform and Tronador as the
component/configuration/build authority. Existing six language templates remain
unchanged. One repository version serves affected component builds; unchanged
artifacts keep their original provenance. No Makefile or root language build is needed.

## Configuration ownership

```text
.cloudopsworks/
  cloudopsworks-ci.yaml       # schemaVersion 2; GitFlow, components, cd.deployments
  vars/inputs-ENV.yaml        # monorepo.targets; existing environment inputs
  values/                    # existing chart values, where needed
  preview.yaml               # trusted Kubernetes-only preview policy
  schemas/                   # identical generated CLI schemas, not editable authority
  examples/vars/              # 17 inactive YAML target examples
  labeler.yml                # generated component labels + preserved custom rules
```

All human pipeline configuration is YAML. Component `targets: [target-id]` binds
IDs, not inline resource definitions. Resource properties belong exactly once in
`vars/inputs-ENV.yaml` under `monorepo.targets.target-id`. Filename supplies the
environment; the map key supplies identity. Do not add `id`, `environment`, or
`configDigest` fields to a target body. There is no external JSON target loader,
`cd.targets`, second credential tree, or imperative shell configuration.

`cd.deployments` keeps familiar develop/dev, test/uat, prerelease/demo,
release/prod and ordered support mappings, enabled flags and qualifier targets.
`targetName` names a deployment; it is not an implicit component target selector.
The legacy optional hotfix mapping is inert migration data, not a new push trigger.
Selection intersects explicit component target IDs with the classified environment
before protected identity/provider resolution. Empty target bindings deploy nothing.
Disabled/missing mappings do not fall back to production.

## Developer journey

```sh
tronador components validate --json
tronador components lifecycle --event push --ref refs/heads/develop --json
tronador components add billing --language ruby --framework rails --dry-run --json
tronador components add billing --language ruby --framework rails --json
tronador components build billing --allow-network --no-install-tools --json
tronador components test billing --allow-network --no-install-tools --json
```

Add creates a new component with `targets: []`; bind an existing environment target
by editing that YAML list. No new workflow, credentials, provider state handle or
backend lock configuration is needed to add a component. Paths are never overwritten.
The mixed template includes Go, Node/npm and Java/Maven; .NET, Python, Rust, plain
Ruby and Rails are real additional scaffolds. Rails standalone generation uses
`tronador components new ../rails-app --language ruby --framework rails` at a fresh
path; it does not mutate a plain Ruby application. Declare exact runtimes and lockfiles.
Build/test/package execute project code and must run without cloud credentials.
`--allow-network` permits dependency resolution, not a security sandbox.

No component addition edits workflow files. Familiar main-build/pr-build/pr-close
and command callers are centralized in Blueprints; the exact thin caller contract is implemented and pinned to v5.11.0. Central
provider/scanner execution and hosted trust verification remain activation gates.

## Existing Go application migration

Preserve GitFlow/GitVersion and `cd.deployments`; move application source into
`components/api`, add the v2 component registry, and retain familiar environment
vars/values. Legacy Go sources embedding VERSION still need that generated build
file. There is no arbitrary legacy-hook/GoReleaser importer. Container/marker/health
adaptation must be reviewed separately before preview activation.

`tests/monorepo/smoke_migration.py` executes this journey against a disposable
copy of the actual Go template, then adds Node, Java, plain Ruby and Rails, builds
and tests each, asserts empty new bindings, binds one preconfigured YAML target,
and verifies unchanged workflow/GitVersion hashes and deployment/GitFlow policy.
This proves local migration/build behavior, not hosted CI/CD or preview readiness.

See [rollout](rollout.md), [CLI boundaries](tronador-design.md),
[configuration ADR](../adr/0005-yaml-gitflow-iac-revision.md) and
[project wiki](../../omx_wiki/index.md).

## Thin caller inventory

Both templates use the frozen `tests/monorepo/fixtures/revision_callers.json`
contract at immutable Blueprints `v5.11.0`, exact job display names, explicit secret
mappings and per-job permission ceilings. No application shell checkout/build
or hosted CLI compilation is embedded in these callers.

- `main-build.yml`: familiar create/develop/support/release/version-tag/manual
  events; root configuration paths are explicitly included after legacy exclusions.
- `pr-build.yml`: original PR types/base filters for untrusted CI (no secrets/OIDC),
  separate trusted workflow_run preview job.
- `pr-close.yaml`: trusted pull_request_target closed adaptation; frozen base policy.
- `slash-commands.yml`, `slash-on-approve.yml`, `slash-on-retry-automerge.yml`,
  `automerge.yml`, `checkpr.yml`, `process-owners.yml`: centralized GitOps helpers.
- `scan.yml`: centralized manual scan.
- `deploy.yml`, `environment-destroy.yml`, `environment-unlock.yml`: explicit
  component/target/protected-environment scoped operations, no implicit all.
- `deploy-container.yml`: explicit component publication, not workload deployment.

Manual `environment` uses GitHub's environment input type and means the **exact
protected environment identity**, not a guessed cloud environment. Every operation
requires component and target. Destroy confirmation is
`destroy <environment>/<target>/<component>`. Unlock additionally requires native
`lock-id` and `unlock <environment>/<target>/<component> <lock-id>` confirmation.
Qualifiers are explicit optional inputs, not arbitrary environment parsing.

Only approval aliases and help/retry commands exposed by the central GitOps helper
are supported. `/retry` reattempts scoped automerge, never an arbitrary CI run;
one comment is consumed once even when that action fails. Submit a new comment
for another retry. Legacy phantom commands fail explicitly as unsupported.
