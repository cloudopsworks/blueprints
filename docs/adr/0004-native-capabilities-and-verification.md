# ADR 0004: Explicit native deployment capabilities

> Historical initial design. Conflicting configuration/execution claims are superseded by [ADR 0005](0005-yaml-gitflow-iac-revision.md); not current provider capability proof.

- Status: accepted for the v5.11 implementation

## Decision

AWS, Google Cloud and Azure adapters execute typed native CLI/API operations
against preconfigured resources. They do not provision landing zones, identities,
registries, clusters or hosting plans. Package/runtime/architecture/handler
compatibility is validated before mutation; a generic application is not silently
converted into a native function.

Native function ZIPs contain prepared runtime dependencies and required layout.
GCP gen2 source deployment remains an explicit provider build mode. Container
artifacts publish by immutable digest; cloud-specific registry promotion preserves
that digest and validates protected destination identity. Lambda images require
same-region ECR. Private image access is a setup requirement, not an assumed
property of GHCR publication.

Readiness combines intended native revision/version evidence with configured
serving or correlated handler completion. Azure Flex uploads exact prepared bytes
with remote build disabled, polls its returned deployment ID, and accepts only
terminal success. It does not invent a provider-returned package hash. Where
required, application verification compares a startup-bound or baked
`{componentId, sourceSha, builtVersion}` tuple to the manifest. An environment echo,
request echo or generic HTTP 200 is not intended-build proof. This is not
cryptographic provider attestation or evidence for every replica.

Native Beanstalk CNAME and S3 website HTTP health use explicitly weaker,
credential-free transport. They do not send secrets or payloads, follow redirects
or disable TLS verification.

## Consequences

Mode-specific limitations are part of the contract, including Flex slot/runtime
restrictions and custom-handler requirements. Offline command/response tests and
local language smokes do not replace staging deployment, readiness and cleanup
acceptance. See [provider evidence](../reference/cloud-command-evidence.md) and the
[rollout runbook](../monorepo/rollout.md).
