# AI Agents Guidelines

This document provides instructions for AI Agents working with the implementations of this Blueprints Master Repository.

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
