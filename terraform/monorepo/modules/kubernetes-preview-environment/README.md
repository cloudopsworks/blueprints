# Preview environment authority

This fixed native root owns **one namespace per repository/PR/target**, four
NetworkPolicies, and exactly three bounded probe Pods. Component Helm releases
remain in their separate states and use the authoritative Blueprint charts.

The only external-namespace writes are the owned control and ingress probe Pods;
their parent namespaces are exact, read-only data references. Probe names are
stable per repository/PR/target, and owner/generation annotations bind them to the
preview namespace. All Pods execute the same fixed repository-owned Python server
on port 8000, using a protected immutable probe image, nonroot identity, no API
token, read-only filesystem, RuntimeDefault seccomp and dropped capabilities.
Runtime verification may read/log/execute fixed connectivity checks against these
Pods and server-side dry-run a forbidden admission request. Neither PR YAML nor
source-provided commands/manifests execute through this root.

The four additive policies deny all ingress/egress by default, permit same-
namespace traffic, permit only protected DNS pods in protected namespaces on
TCP/UDP 53, and permit only the intended protected ingress namespace **and** pod
selectors. Policy presence is not CNI proof: runtime must verify paired allowed/
denied traffic, DNS, provider metadata denial, and restricted admission before
component rollout. Failed verification still requires guarded native cleanup.

## Internal renderer seam

`resource`, `configuration`, `workload`, `artifact`, and `owner_digest` use the
existing renderer contract. `namespace`, `repository_id`, `pr_number`, `target_id`,
`kubeconfig_path`, and the closed `isolation` projection are trusted derived
inputs—not new human-editable fields. `isolation.ingressNamespace` must already
have been uniquely API-resolved from the protected selector.

`owned` returns namespace, namespace UID, owner digest, policy IDs and each probe's
ID/name/namespace/UID. Persist the native handle before init; independently bind
that UID to private native state and API ownership after create. Unknown existing
ownership is not permission to import or adopt.

## Cleanup boundary

Native graph dependencies delete owned probes/policies before the namespace.
Shared orchestration must first destroy component states and recheck fresh PR,
cluster, historical UID, native/API ownership and exact selection immediately
before **every** saved apply under the single fixed verified concurrency group.
Keep recovery handles on failure/uncertainty; never refresh the historical UID to
match a replacement or use a direct mutation fallback.

Kubernetes provider **2.38.0** uses empty namespace `DeleteOptions`: this root does
**not** promise atomic UID-conditional deletion. The accepted normal single-writer
boundary cannot atomically exclude privileged out-of-band replacement after the
last read, or undo an already submitted operation after PR reopen. Local mocks
and offline provider plans do not establish live CNI, hosted scheduling, or
credentialed readiness. Activation remains gated in `inputs.json`.
