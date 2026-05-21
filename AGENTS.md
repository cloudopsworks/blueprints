# AI Agents Guidelines

This document provides instructions for AI Agents working with the implementations of this Blueprints Master Repository.

## General Guidelines
- **Use make as provided**: All commands should be run from the root of the repository.
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
- Use `make` targets whenever available for branch and release operations.
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

Module versioning follows GitHub Flow — a simplified branching model where feature branches are created from and merged back into `master`. Use `make` targets whenever available for branch and release operations.
- There is a skill related to this template module and their implementations, it can be found in the [Claude Code Skills - cw-release](https://github.com/cloudopsworks/claude-code-skills/tree/main/cw-release) can be used in any agent anyway, install and use it.
- The cw-release may not update .cloudopsworks/_VERSION file, so you should run `make gitflow/version/file` to make this update before the merging of the release/feature/patch process, make sure the content format is plain vX.Y.Z, this is mandatory.
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
- Run the minor tagging process to create a new tag and release:
  ```sh
  make tag
  ```
  this will push the proper minor versioning tag to the repository as vX.Y

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

All new features and provider version upgrades branch directly from `master` using the no-develop targets:

1. Create a feature branch from `master`:
   ```sh
   make gitflow/feature/start-no-develop:<feature-name>
   ```
2. Implement changes and validate:
   ```sh
   make fmt
   make lint
   ```
3. **Publish first**, then finish — the finish step requires the branch to exist on the remote:
   ```sh
   make gitflow/feature/publish:<feature-name>         # push branch to remote (required before finish)
   make gitflow/feature/finish-no-develop:<feature-name>  # creates the PR
   ```

### Minor Fixes and Documentation Updates (Patch)

Workflow upgrades and documentation-only fixes are patch-level changes and use the **hotfix** branch type, not feature branches:

1. Start a hotfix branch from `master`:
   ```sh
   make gitflow/hotfix/start
   ```
2. Apply changes (run `make repos/upgrade` for template upgrades, then update docs as needed):
   ```sh
   make repos/upgrade   # pulls latest template version
   # edit .boilerplate/inputs.yaml, README.yaml, etc.
   make readme          # regenerate README.md last
   ```
3. Commit using conventional commits with `+semver: patch`:
   ```sh
   git commit -m "docs: sync inputs.yaml and update docs +semver: patch"
   ```
4. **Publish first**, then finish — the finish step requires the branch to exist on the remote:
   ```sh
   make gitflow/hotfix/publish   # push branch to remote (required before finish)
   make gitflow/hotfix/finish    # creates the PR
   ```
5. Wait for all CI checks to pass, then merge with `gh` CLI (see [PR Merge Guidelines](#pr-merge-guidelines)).

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

| Change Type                               | Branch Type | Merges Into | Make Target             | Semver Impact | Annotation                          |
|-------------------------------------------|-------------|-------------|-------------------------|---------------|-------------------------------------|
| Documentation fix / inputs.yaml sync      | `hotfix`    | `master`    | —                       | PATCH         | `+semver: patch`                    |
| New feature                               | `feature`   | `master`    | —                       | MINOR         | `+semver: feature`                  |
| Bug fix                                   | `feature`   | `master`    | —                       | PATCH         | `+semver: fix`                      |
| Breaking / incompatible change (MAJOR bump) | `feature`   | `master`    | —                       | MAJOR         | `+semver: major`                    |
| Breaking / incompatible change (minor-compatible)| `feature`   | `master`    | —                       | MINOR         | `+semver: breaking`                 |


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
- **README.md generation**: Run `make readme` as the **last step** after all documentation updates are complete.
