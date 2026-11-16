# AI Agents Guidelines

This document provides instructions for AI Agents working with the implementations of this Blueprints Master Repository.

## Schema-v2 monorepo maintenance

- Read [the v5.11 guide](docs/monorepo/guide.md), [ADRs](docs/adr/0001-schema-v2-component-authority.md)
  and [rollout limits](docs/monorepo/rollout.md) before changing the new lifecycle.
- Keep application callers thin. Central workflows own lifecycle orchestration;
  Tronador owns source YAML normalization, selection, scaffolding and typed builds.
  Do not add another YAML resolver or executable shell fields to component config.
- `kubernetes/helm/charts` is authoritative for normal and preview workloads.
  Extend opt-in values; do not fork a sandbox chart. Preserve legacy default renders.
- Keep source builds free of deployment secrets/OIDC. Privileged paths consume
  validated artifacts as data, never PR scripts, charts or source generators.
- Preserve one repository version and honest carried artifact provenance. Deployment
  convergence requires intended readiness plus durable actor-filtered receipts.
- Test Go/Python contract parity, affected selection, immutable release failure,
  provider modes, preview trust/isolation/cleanup and chart compatibility. Report
  mocked/static/local evidence separately from hosted/cloud proof.
- Existing single-application templates and legacy action contracts remain compatible;
  no implicit migration or unrelated template edits. New templates use no Makefile.
- `README.yaml` is maintained source; regenerate `README.md` through Tronador.
  Keep ADRs and `omx_wiki/` links current. CLI software version is not a template marker.
- Release/push/tag/cloud operations require their own task authority. The following
  existing release policies describe authorized release work, not an instruction to
  publish an implementation branch automatically.

## v5.11 operational revision overrides

- Human config remains YAML in cloudopsworks-ci.yaml and vars/inputs-ENV.yaml monorepo.targets. Component targets are IDs only; no cd.targets loader or duplicated credentials tree.
- Application lifecycle keeps familiar GitFlow/cd.deployments; this does not change this Blueprints repository's own release branching policy below.
- Terraform/Terragrunt owns workload mutation and persistent preview children; external parents are not implicitly adopted. Explicit managed-child ownership is required.
- Required completed scans precede public publication and workload mutation; pending/upload success is not scan completion.
- Destroy/unlock must recover historical verified StateHandles/native locks. Never export raw plan/state/generated trees/secret diagnostics.
- Revised callers/provider P0 remain activation-gated. Do not claim 17 examples prove provider execution. Hosted jobs install exact released CLI binaries, never compile source/latest.
- ADR0005 supersedes conflicting initial ADR0001–4 details; keep docs honest about local/provider/hosted/live evidence.

## General Guidelines
- **Use the `tronador` CLI**: All `make` targets (Tronador Makefile includes) are **deprecated**. Use the `tronador` CLI
  (distributed from the `tronador-cli` project) for all branch, version, release, template and README operations.
  Run commands from the root of the repository (or pass `--workdir`). Use `--dry-run` to preview any operation,
  and `tronador <command> --help` to discover flags.
  - Only fall back to a `make` target when no `tronador` equivalent exists, and say so explicitly.
- **Mandatory Header**: Each .tf file must start with the following copyright header:
  ```hcl
  ##
  # (c) 2021-2026
  #     Cloud Ops Works LLC - https://cloudops.works/
  #     Find us on:
  #       GitHub: https://github.com/cloudopsworks
  #       WebSite: https://cloudops.works
  #     Distributed Under Apache v2.0 License
  #
  ```
- **Repository Management**
    - Use process as described in the contributing guidelines: [GitHub Flow](https://cloudopsworks.co/resources/githubflow-way-of-work/)
- **Never push directly to `master`**. All changes must flow through feature or hotfix branches and be merged via pull requests.
- Branches must be created before any change is committed.
- Follow [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`) for all module tags.
- There is no `develop` branch — all work flows directly through feature branches to `master`. This approach simplifies the development workflow and enables continuous integration and deployment from the main branch.
- Avoid in the commit comments explicitly mentioning `+semver:` changes within changesets, describe it with other words. The semver annotations should only be present in commit messages and PR descriptions to trigger the correct version bump in CI.
- Avoid scrubbing into Makefile or tronador utility scripts.
- Use `tronador versions ...` commands for branch and release operations (never the deprecated `make gitflow/*` targets).
- Use `gh` cli for PR merging and release management.
    - When waiting for a PR status check to pass, use `gh pr checks <number> --watch`
- Plan consistently and thoroughly before starting any work.

## Versioning Management

> **GUARDRAIL — Version Bump Policy**
>
> **Never** use `+semver: minor`, `+semver: feature`, `+semver: breaking`, or `+semver: major` annotations
> unless the user has **explicitly** requested a minor or major version bump in the current conversation.
> When in doubt, default to `+semver: patch` / `+semver: fix`.
> This applies to commit messages, PR titles, PR bodies, and merge commands.
> If you believe a change warrants a minor or major bump, **ask the user first** before applying the annotation.

Module versioning follows GitHub Flow — a simplified branching model where feature branches are created from and merged back into `master`. Use `tronador versions` commands for branch and release operations.
- There is a skill related to this template module and their implementations, it can be found in the [Claude Code Skills - cw-release](https://github.com/cloudopsworks/claude-code-skills/tree/main/cw-release) can be used in any agent anyway, install and use it. When the skill suggests a `make` target, use the `tronador` equivalent from the [command mapping](#make-to-tronador-command-mapping) instead.
- The cw-release may not update .cloudopsworks/_VERSION file, so you must update it (see override below) before the merging of the release/feature/patch process, make sure the content format is plain vX.Y.Z, this is mandatory.
- **Every merge to `master` is a release** (the `pr-merge-tagging` workflow tags it), so **every** feature, hotfix
  or release branch must carry a committed `_VERSION` update. There is no "docs only, no release" exception.

> **OVERRIDE — _VERSION File Generation (this repository)**
>
> This repository has `isTemplate=false`, which would normally suppress the `_VERSION` update guard in `cw-release`.
> **Ignore that guard unconditionally.** Always update `.cloudopsworks/_VERSION` before any PR merge or release finish,
> regardless of what `cw-release` detects about `isTemplate`. The `.cloudopsworks/_VERSION` file must be committed
> and present with format `vX.Y.Z` for every release branch before merging.
>
> **Before starting a branch** — make sure the previous release was actually tagged. If `master` has
> commits past the latest tag that were meant as a release (e.g. a failed `pr-merge-tagging` run), fix
> and re-release that first; otherwise the branch version and the tag CI creates will not match.
> ```sh
> git checkout master && git pull origin master && git fetch --tags
> git describe --tags --abbrev=0                                                   # latest tag
> gitversion -config .cloudopsworks/gitversion.yaml -showvariable MajorMinorPatch  # must equal latest tag (without v)
> ```
>
> **On the branch, after the last content commit and before `publish`/`finish`:**
> ```sh
> git fetch origin --tags --prune
> tronador project version --generate --yes     # writes v<MajorMinorPatch> to .cloudopsworks/_VERSION
> cat .cloudopsworks/_VERSION                   # must print vX.Y.Z (hotfix: must match the hotfix/vX.Y.Z branch name)
> git add .cloudopsworks/_VERSION
> git commit -m "chore: Version Bump"
> ```
> If the CLI refuses (`project_version_marker_unsupported`), write the same value from GitVersion:
> ```sh
> printf 'v%s\n' "$(gitversion -config .cloudopsworks/gitversion.yaml -showvariable MajorMinorPatch)" > .cloudopsworks/_VERSION
> ```
>
> **Before merging the PR** — confirm the file is in the PR: `gh pr diff <PR_NUMBER> --name-only | grep .cloudopsworks/_VERSION`.
> Do not merge without it.
>
> **After the release** — verify the tag CI created matches the file:
> ```sh
> git checkout master && git pull origin master && git fetch --tags
> test "$(cat .cloudopsworks/_VERSION)" = "$(git describe --tags --abbrev=0)" && echo OK || echo MISMATCH
> ```
> On `MISMATCH`, report it; never hand-edit `_VERSION` on `master` — the next release branch corrects it.

After the completion of a version release, merging and all release workflow completions, the agent should run minor tagging process (will tag as vX.Y):
- Is a reference to the latest release tag, for example, if the latest release is v5.10.39, the tagging process will create a new tag v5.10
- No release notes or release should be created, only the tag will be automatically pushed.
- Switch to master and pull latest changes:
  ```sh
  git checkout master
  git pull origin master
  ```
- Ensure we are at the latest tag:
  ```sh
  git fetch --tags
  git describe --tags --abbrev=0
  ```
- Create and force-push the floating minor tag (replaces the deprecated `make tag`; `tronador versions tag`
  only creates full `vX.Y.Z` tags, so the minor tag is created with `git`):
  ```sh
  LATEST=$(git describe --tags --abbrev=0)   # e.g. v5.10.39
  MINOR=${LATEST%.*}                          # e.g. v5.10
  git tag -f "$MINOR" "$LATEST^{commit}"     # point at the commit, not the annotated tag object
  git push origin -f "$MINOR"
  ```
  this pushes the proper minor versioning tag to the repository as vX.Y

### Semver Commit Annotations
To trigger the correct version bump in CI, include a semver annotation in your commit message or PR description:

| Change Type        | Annotation keywords                                           |
|--------------------|---------------------------------------------------------------|
| Major change only  | `+semver: major`                                              |
| Minor / feature    | `+semver: minor` or `+semver: feature` or `+semver: breaking` |
| Fix / patch        | `+semver: fix` or `+semver: patch` or `+semver: hotfix`       |

> **Note:** `+semver: breaking` triggers a **MINOR** bump (per GitVersion config), not MAJOR. Use `+semver: major` will be explicitly directed to use.

Example commit messages:
Use conventional commit style.
```
feat: add support for VPC endpoints +semver: minor
fix: correct IAM policy ARN +semver: fix
refactor!: remove deprecated outputs +semver: breaking
```

### New Features

All new features and provider version upgrades branch directly from `master` (the CLI detects GitHub Flow and uses the main branch — no `-no-develop` variants are needed):

1. Create a feature branch from `master`:
   ```sh
   tronador versions feature start <feature-name>
   ```
2. Implement changes and validate (e.g. `terraform fmt -recursive` for Terraform content, `tronador readme lint` for docs).
3. **Update and commit `.cloudopsworks/_VERSION`** (mandatory — see [_VERSION override](#versioning-management)):
   ```sh
   tronador project version --generate --yes
   git add .cloudopsworks/_VERSION && git commit -m "chore: Version Bump"
   ```
4. **Publish first**, then finish — the finish step requires the branch to exist on the remote:
   ```sh
   tronador versions feature publish    # push branch to remote (required before finish); name inferred from feature/*
   tronador versions feature finish     # creates the guarded PR to master
   ```

### Minor Fixes and Documentation Updates (Patch)

Workflow upgrades and documentation-only fixes are patch-level changes and use the **hotfix** branch type, not feature branches:

1. Start a hotfix branch from `master` (next patch version is calculated from GitVersion):
   ```sh
   tronador versions hotfix start
   ```
2. Apply changes (run `tronador repos upgrade` for template upgrades, then update docs as needed):
   ```sh
   tronador repos upgrade   # pulls latest template version in the current major/minor line
   # edit .boilerplate/inputs.yaml, README.yaml, etc.
   tronador readme build    # regenerate README.md last
   ```
3. Commit using conventional commits with `+semver: patch`:
   ```sh
   git commit -m "docs: sync inputs.yaml and update docs +semver: patch"
   ```
4. **Update and commit `.cloudopsworks/_VERSION`** (mandatory — must equal the `hotfix/vX.Y.Z` branch version):
   ```sh
   tronador project version --generate --yes
   git add .cloudopsworks/_VERSION && git commit -m "chore: Version Bump"
   ```
5. **Publish first**, then finish — the finish step requires the branch to exist on the remote:
   ```sh
   tronador versions hotfix publish   # push branch to remote (required before finish)
   tronador versions hotfix finish    # creates the guarded PR (never use --local here; merges go through PRs)
   ```
6. Wait for all CI checks to pass, confirm `_VERSION` is in the PR diff, then merge with `gh` CLI (see [PR Merge Guidelines](#pr-merge-guidelines)).
7. After CI tags the release, run the post-release `_VERSION` check and the minor tagging process above.

### PR Merge Guidelines

After all CI checks pass, merge using `gh pr merge` with a proper merge commit:

```sh
gh pr merge <PR_NUMBER> --repo <owner/repo> --merge \
  --subject "chore: merge <branch> - <short description> +semver: patch" \
  --body "$(cat <<'EOF'
## Summary

- Bullet point summary of changes

+semver: patch
EOF
)" --delete-branch=false
```

Key rules:
- Always use `--merge` (never `--squash` or `--rebase`) to preserve commit history.
- Include `+semver: <level>` in the **body** (not just the title) so GitVersion picks it up.
- Use `--delete-branch=false` when you only want to delete the local branch (do so separately with `git branch -d <branch>`).
- After merge, checkout and pull master: `git checkout master && git pull origin master`.


### Summary Table

| Change Type                                       | Branch Type | Merges Into | Start Command                          | Semver Impact | Annotation          |
|---------------------------------------------------|-------------|-------------|----------------------------------------|---------------|---------------------|
| Documentation fix / inputs.yaml sync              | `hotfix`    | `master`    | `tronador versions hotfix start`       | PATCH         | `+semver: patch`    |
| New feature                                       | `feature`   | `master`    | `tronador versions feature start <n>`  | MINOR         | `+semver: feature`  |
| Bug fix                                           | `feature`   | `master`    | `tronador versions feature start <n>`  | PATCH         | `+semver: fix`      |
| Breaking / incompatible change (MAJOR bump)       | `feature`   | `master`    | `tronador versions feature start <n>`  | MAJOR         | `+semver: major`    |
| Breaking / incompatible change (minor-compatible) | `feature`   | `master`    | `tronador versions feature start <n>`  | MINOR         | `+semver: breaking` |

### Make to Tronador Command Mapping

All `make` targets below are **deprecated**. Use the `tronador` command instead.

| Deprecated `make` target                         | `tronador` CLI replacement                                  |
|--------------------------------------------------|-------------------------------------------------------------|
| `make gitflow/feature/start-no-develop:<name>`   | `tronador versions feature start <name>`                    |
| `make gitflow/feature/publish:<name>`            | `tronador versions feature publish [name]`                  |
| `make gitflow/feature/finish-no-develop:<name>`  | `tronador versions feature finish [name]`                   |
| `make gitflow/hotfix/start`                      | `tronador versions hotfix start`                            |
| `make gitflow/hotfix/publish`                    | `tronador versions hotfix publish`                          |
| `make gitflow/hotfix/finish`                     | `tronador versions hotfix finish`                           |
| `make gitflow/release/*`                         | `tronador versions release start\|publish\|finish`          |
| `make gitflow/version/tag`                       | `tronador versions tag [qualifier] --publish`               |
| `make gitflow/version/file`                      | `tronador project version --generate --yes` (see [_VERSION override](#versioning-management)) |
| `make tag` (minor `vX.Y` tag)                    | `git tag -f vX.Y vX.Y.Z && git push origin -f vX.Y` (no CLI equivalent) |
| `make repos/upgrade[/<version>]`                 | `tronador repos upgrade [version]`                          |
| `make readme`                                    | `tronador readme build`                                     |
| `make readme/lint`                               | `tronador readme lint`                                      |
| `make init`                                      | `tronador readme init` / `tronador readme deps`             |
| `make docs/terraform.md`                         | `tronador docs terraform`                                   |
| `make docs/targets.md`                           | `tronador docs targets`                                     |


## Documentation Guidelines
> Act as an expert technical writer and documentation specialist of Cloud Ops Works Pipeline Blueprints development team
> All documentation must be clear, concise, and accurate.
- **Source file**: Documentation is maintained in `README.yaml`. Inner sections may use Markdown formatting.
- **Badges**:
    - If the module has a public repository, include badges for Latest Release and Last Updated, linking to the appropriate GitHub owner/repo.
    - Locate it between the `name` or `logo` and `license` fields.
    - Template:
      ```yaml
      badges:
        - name: Latest Release
          image: https://img.shields.io/github/release/<owner/repo>.svg?style=for-the-badge
          url: https://github.com/<owner/repo>/releases/latest
        - name: Last Updated
          image: https://img.shields.io/github/last-commit/<owner/repo>.svg?style=for-the-badge
          url: https://github.com/<owner/repo>/commits
      ```
- **README.yaml fields**: Once inline documentation is complete, update `README.yaml` to properly document the following fields:
    - `name`
    - `description`
    - `introduction`
    - `usage` — write examples using Terragrunt HCL; avoid plain Terraform HCL.
        - Lead with the Terragrunt scaffolding workflow (see [Terragrunt Scaffolding in Usage Examples](#terragrunt-scaffolding-in-usage-examples) below).
        - After scaffolding, show the resulting `inputs.yaml` with all module-specific variables from `.boilerplate/inputs.yaml`, fully commented per the `(Required)`/`(Optional)` style.
        - Show the rendered `terragrunt.hcl` as generated by scaffold — including the `locals` block that loads `inputs.yaml` as `local.local_vars` and the `inputs` block mapping each variable. Do not hand-author the `terragrunt.hcl` from scratch; represent what scaffold produces.
        - Include all module variables with their full inline-documented YAML structure mirroring `.boilerplate/inputs.yaml`.
    - `examples` and `quickstart`
- **Updates**: Apply the same criteria above whenever new variables or resources are added to the module.
    - copyrights.year: if not specified or blank, set "2021", should be an year not a range, if there is a year specified leave it as is.
    - badges: adjust the badge.image links to point to the correct repository (owner/repo).
- **README.md generation**: Run `tronador readme build` as the **last step** after all documentation updates are complete (the `make readme` target is deprecated). Verify with `tronador readme lint`.

## App Engine amendment guardrails

Fresh exclusive nondefault whole-service/versions/traffic ownership is mandatory;
application/default service/project/bucket/IAM remain external. Deliberate same-mode
recreation downtime is accepted; no old false-state adoption or cross-standard/flex.
Require existing operator single-writer controls. Unknown timeout survivors retain
historical claims and require reviewed reconciliation, never auto-import/delete/blind
retry. Exact-byte app.yaml projection is generated, never human appConfigResolved;
entrypoint must be explicit or existing iac.entrypoint fallback. Gen2 eventSource
is derived, not a new source setting. Azure public-endpoint/whole-API/hierarchical
slot boundaries and local-versus-live proof remain explicit in rollout documentation.

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
