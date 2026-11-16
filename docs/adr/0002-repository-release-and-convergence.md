# ADR 0002: One version, two selection decisions

> Historical initial design. Conflicting configuration/execution claims are superseded by [ADR 0005](0005-yaml-gitflow-iac-revision.md); not current provider capability proof.

- Status: accepted for the v5.11 implementation

## Decision

A repository has one version, tag and complete release manifest. Source builds
select affected components and reverse-transitive dependants. Release selection
compares against the previous verified, complete, published release—not the last
push or an interrupted draft. Verified unchanged artifacts carry forward with their
original `sourceSha` and `builtVersion`.

Publication uses a resumable draft. All selected results must succeed, artifact
identities must verify, and the complete manifest must pass read-back before the
release is published. A conflicting tag, asset or manifest fails rather than
silently replacing provenance. OCI identity is the selected descriptor digest;
ZIP, tar and specification identity is the digest of exact bytes.

Deployment is a separate convergence decision. Resolve every active binding and
check canonical resource ownership before mutation. Compare desired artifact plus
effective target/workload/readiness configuration with actor-filtered, durable
GitHub Deployment receipts. A failed/unresolved newer attempt forces retry even
when source did not change. A new target or configuration-only change deploys
existing artifacts without inventing a source rebuild.

## Consequences

- A successful build or native management command is not deployment success.
- Native readiness and configured serving/handler probes must pass, and success
  status must be durably read back before a receipt can suppress another deploy.
- Removing a component does not implicitly destroy production resources.
- There are no independent component release counters or tags.

See [release and deployment](../monorepo/guide.md#release-and-deployment).
