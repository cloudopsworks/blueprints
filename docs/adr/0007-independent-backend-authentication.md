# ADR 0007: independent backend/workload authentication

Status: approved bounded amendment; implementation/interface/native/hosted verification pending.
Original five review pairs and accepted App Engine/preview decisions remain intact.

## Decision

Reuse native S3/GCS/Azure auth_ref and the same protected AUTH map, independently
of target authRef. Fresh generated descriptors freeze separate backendIdentity and
selected aliases; no new human identity field, map, flag or component ceremony.
Authenticate only the selected pair and capture private separate contexts. Native
state/locks use backend context; workload/registry/readiness use workload context.

Legacy implicit S3/GCS is same-workload-principal only. Azure old triple refs must
be one unambiguous same binding; tenant was not historically frozen. Never infer
cross-cloud/distinct-principal migration or retarget historical backend from current
YAML. Backend identity is credential context, not bucket/storage ownership proof.

Entire private backend/plan/native-cache trees are secret-bearing and non-exportable.
Temporary credentials and native precedence require actual execution evidence; this
approved contract is not implementation success or live OIDC proof. See
[detailed compatibility and security limits](../monorepo/rollout.md#independent-workload-and-backend-authentication).
