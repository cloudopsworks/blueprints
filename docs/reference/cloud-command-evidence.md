# v5.11 native deployment adapters — command evidence and validation boundary

> Historical pre-revision direct-adapter evidence only. NOT the current activation contract.
> The operational revision requires authoritative Terraform/Terragrunt, managed-child ownership,
> provider mode/schema/plan proof and the gates in [ADR0005](../adr/0005-yaml-gitflow-iac-revision.md)
> and [rollout](../monorepo/rollout.md). The commands below do not establish revised support.

## Historical execution contract

The trusted Python adapters live under `cd/monorepo/runtime/providers/`.
`resolve(request, executor)` is read-only and returns `providerIdentity`, canonical
`resourceClaims`, and a native `resource` snapshot. Resolve **all** active bindings
and reject ownership collisions before any component mutation. `deploy(request,
executor, context=..., resolved=...)` re-resolves identity before mutation and
returns a validated DeploymentResult, never a receipt. Orchestration supplies the
expected account identity and verifies complete release/configuration provenance.

Internal trusted context (not extra wire fields): `artifactPath` is the verified,
downloaded immutable release asset; `workDir` is a private parent directory;
`chartPath` is the authoritative `kubernetes/helm/charts` source (opt-in
`monorepo.enabled` generated values), never a copied chart fork; `secrets` resolves protected header refs;
`hostKeys[ref]` contains `value`, exact slot `resourceId`, `keyName: _master`, and
verified `hostname`. Tests may inject `http`, `clock`, `sleep`, and `forward`.
Never load these capabilities from component/source artifacts. Runner is argv-only,
checks return codes, bounds output, redacts process failure diagnostics, and must
have a command timeout no greater than the target readiness deadline.

Downloaded ZIP/tar/spec bytes are validated before use; container references are
immutable `@sha256:` references. Deployments use stable idempotency-key-derived
native revision labels. Static sync never deletes unrelated objects; the reserved
`.cloudopsworks-release.json` marker uploads last, and serving verification compares
every package file and the marker. The package cannot contain that reserved path.
API probes must name an operation in the actual published OpenAPI artifact.

## Command authority

Read-only local version/help checks on 2026-11-12: AWS CLI **2.40.1**, Azure CLI
**2.90.0**, Google Cloud SDK **553.0.0**, kubectl **1.37.2**, Helm **4.3.1**.
These are evidence versions, not an assertion of credentialed staging validation.
Provider deploy commands have **not** been run against live cloud resources.

| Target | Actual update + native verification | Official command reference |
|---|---|---|
| AWS EKS | job-local kubeconfig; fixed Helm chart; desired image/port; revision-pinned rollout; owned Service loopback probe | [EKS credentials](https://docs.aws.amazon.com/cli/latest/reference/eks/update-kubeconfig.html), [rollout revision](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_rollout/kubectl_rollout_status/) |
| AWS Beanstalk | S3 bundle; create deterministic application version only if absent; update environment, wait, exact version + green health; native CNAME health GET | [create version](https://docs.aws.amazon.com/cli/latest/reference/elasticbeanstalk/create-application-version.html), [update](https://docs.aws.amazon.com/cli/latest/reference/elasticbeanstalk/update-environment.html) |
| AWS Lambda | existing package/runtime/architecture; optimistic revision-id update, publish, waiter, exact immutable version/code hash; optional existing alias update; synchronous invocation requires executed version/no FunctionError/body match | [update code](https://docs.aws.amazon.com/cli/latest/reference/lambda/update-function-code.html), [invoke](https://docs.aws.amazon.com/cli/latest/reference/lambda/invoke.html) |
| AWS S3 static | owner preflight; scoped sync without delete/follow-symlinks; final marker + byte serving checks | [sync](https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html) |
| AWS REST API Gateway | merge specification with fail-on-warnings; create deployment for stage; exact stage deploymentId; edge operation probe | [put REST API](https://docs.aws.amazon.com/cli/latest/reference/apigateway/put-rest-api.html), [deployment](https://docs.aws.amazon.com/cli/latest/reference/apigateway/create-deployment.html) |
| GCP GKE | project resolution, cluster credentials, same fixed chart and rollout/Service proof | [get credentials](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/get-credentials) |
| GCP Cloud Run | immutable image, runtime SA/declared port, deterministic revision; Ready + observedGeneration + intended image/revision + 100% traffic; HTTPS service probe | [deploy](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy), [describe](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/describe) |
| GCP App Engine | published package appConfig; explicit version/promote; SERVING + service traffic allocation; version URL probe; no invented region deploy flag | [deploy](https://docs.cloud.google.com/sdk/gcloud/reference/app/deploy), [version](https://docs.cloud.google.com/sdk/gcloud/reference/app/versions/describe) |
| GCP Functions gen2 | existing runtime/entry/trigger preflight; gen2 deploy from verified package, runtime SA; describe **--v2**, ACTIVE/config/release + latest traffic; HTTP or correlated typed trigger | [deploy](https://docs.cloud.google.com/sdk/gcloud/reference/functions/deploy), [describe](https://docs.cloud.google.com/sdk/gcloud/reference/functions/describe) |
| GCP Storage static | project/website prerequisites, recursive scoped rsync without deletion, final marker + HTTPS object bytes | [rsync](https://docs.cloud.google.com/sdk/gcloud/reference/storage/rsync) |
| GCP API Gateway | existing API preflight; global immutable config create, gateway update using **--location**; exact ACTIVE config + gateway HTTPS probe | [create config](https://docs.cloud.google.com/sdk/gcloud/reference/api-gateway/api-configs/create), [update gateway](https://docs.cloud.google.com/sdk/gcloud/reference/api-gateway/gateways/update) |
| Azure AKS | exact subscription/ARM cluster, job-local user credentials, kubelogin azurecli; same fixed-chart proof, never --admin | [AKS](https://learn.microsoft.com/en-us/cli/azure/aks#az-aks-get-credentials), [kubelogin](https://azure.github.io/kubelogin/concepts/login-modes/azurecli.html) |
| Azure Container Apps | existing app/container; image/revision update; declared ingress port; **Provisioned**, Healthy, intended container image + 100% traffic; native FQDN probe | [update](https://learn.microsoft.com/en-us/cli/azure/containerapp#az-containerapp-update), [revision](https://learn.microsoft.com/en-us/cli/azure/containerapp/revision#az-containerapp-revision-show), [ingress](https://learn.microsoft.com/en-us/cli/azure/containerapp/ingress) |
| Azure App Service | current container flags or synchronous tracked ZIP deployment; intended config/native deployment status; exact slot + HTTPS bound default host | [container](https://learn.microsoft.com/en-us/cli/azure/webapp/config/container), [deploy](https://learn.microsoft.com/en-us/cli/azure/webapp#az-webapp-deploy) |
| Azure Functions | existing runtime/plan/host.json/custom-handler preflight; premium/dedicated config-zip (seconds), or immutable container config; exact app/slot; HTTP or administrative completion proof | [ZIP](https://learn.microsoft.com/en-us/cli/azure/functionapp/deployment/source#az-functionapp-deployment-source-config-zip), [container](https://learn.microsoft.com/en-us/cli/azure/functionapp/config/container) |
| Azure Blob static | existing account/static hosting, login data plane, literal `$web`, scoped destination path, marker last, verified primary web endpoint bytes | [upload batch](https://learn.microsoft.com/en-us/cli/azure/storage/blob#az-storage-blob-upload-batch) |
| Azure APIM | resolved API logical identity; import OpenApiJson/OpenApi as appropriate; wait uses **--name** vs import **--service-name**; current API/path + gateway HTTPS operation | [API](https://learn.microsoft.com/en-us/cli/azure/apim/api) |

## Serving, asynchronous handler, and transport boundaries

Remote probes do not follow redirects, disable TLS checks, accept arbitrary origin
URLs, or print raw bodies/logs/credentials. GCP audience tokens bind the native
origin. Kubernetes forwarding binds only 127.0.0.1 to the component Service and
terminates/reaps the child in a finally block. Cloud prerequisite setup is outside
this adapter: existing projects/accounts/apps/clusters/hosting, IAM, registries,
networking and runtime profiles must already be configured.

Beanstalk's native CNAME and AWS S3's native website endpoints are narrow HTTP
exceptions: credential-free requests only; Beanstalk only empty-body GET. They
provide weaker transport assurance (`native-cname-http`), not TLS authentication,
and supplement rather than replace authenticated native version/health checks.

GCP Eventarc probes publish a unique nonce/digest/release envelope to the declared
Pub/Sub topic or a unique storage-finalize object. Fixed Cloud Logging filters and
structured completion fields must bind the deployed revision; publish acceptance
alone is failure. Storage cleanup removes only that nonce-specific object.
See [topic publish](https://docs.cloud.google.com/sdk/gcloud/reference/pubsub/topics/publish)
and [logging read](https://docs.cloud.google.com/sdk/gcloud/reference/logging/read).

Azure non-HTTP probes require the **exact app/slot `_master` administrative key**,
not a normal function/host key, and a verified slot hostname. Admin202 requires a
nonce/digest/release/function/resource-correlated structured completion from a fixed
Application Insights query. See [manual invocation](https://learn.microsoft.com/en-us/azure/azure-functions/functions-manually-run-non-http)
and [App Insights queries](https://learn.microsoft.com/en-us/cli/azure/monitor/app-insights#az-monitor-app-insights-query).

## Flex and intended-serving proof closure

The adapter bypasses the Azure CLI Flex `config-zip` wrapper because that wrapper
loses the deployment ID and can implicitly rebuild Python source. It sends the
exact previously hashed ZIP bytes using AAD to the ARM-discovered `Repository`
SCM hostname, with `remoteBuild=false&deployer=blueprints`. Only HTTP202 with a
bounded deployment ID is accepted; it polls that **exact ID**, requires matching
ID/status4, and rejects cancellation/failure/conflict/partial success, missing
status, foreign IDs and 404. No `latest` polling or 202→404 success fallback.

Pinned upstream authority:
- [Azure/functions-action OneDeploy transport, commit6642d253](https://github.com/Azure/functions-action/blob/6642d253e29c8c3c5ebe4d6115069acd17e381cf/src/appservice-rest/Kudu/azure-app-kudu-service.ts)
  documents raw ZIP POST, body deployment ID and the exact-ID endpoint.
- [Azure CLI AAD SCM token audience, commitdc50d475a00ded4a1a1980d4a10a9fbd9a750a81](https://github.com/Azure/azure-cli/blob/dc50d475a00ded4a1a1980d4a10a9fbd9a750a81/src/azure-cli/azure/cli/command_modules/appservice/custom.py)
  establishes `https://appservice.azure.com` rather than a guessed ARM audience.

Flex currently permits production-slot prepared ZIPs for its supported built-in
runtime profile; it rejects named slots, container mode, generic custom handlers
and unestablished native Go profiles **before upload**. Existing native runtime
name/version and hosting tier must match. Premium/dedicated custom-handler ZIPs
require host.json metadata naming a packaged executable with executable mode.
Prepared Python ZIPs require native handler metadata and must include their
runtime dependencies (`.python_packages/lib/site-packages` when applicable).
Provider deployment never rebuilds prepared ZIPs; GCP gen2 source-build mode is
explicitly different. Native invocation and handler completion still gate success.

A successful Flex upload or App Service image configuration/Running state does
not prove which application bytes serve. These paths additionally require a
**build-baked**, literal marker at `/.well-known/cloudopsworks-build.json`:

```json
{"componentId":"api","sourceSha":"<artifact.sourceSha>","builtVersion":"<artifact.builtVersion>"}
```

No extra keys are accepted. The expected tuple comes from the immutable artifact
provenance, not the current release head/version (unchanged artifacts may be
reused). The tuple is baked before package hashing, avoiding a self-referential
artifact digest. Generated scaffolds copy/serve this literal file; custom
Dockerfiles/apps must do the same. A runtime environment echo is not equivalent.
Non-HTTP Azure completions instead include literal `build_componentId`,
`build_sourceSha`, and `build_builtVersion` customDimensions alongside the unique
invocation completion. This proves the observed response is associated with the
manifest's build tuple; it is **not cryptographic attestation of every replica**.

Lambda retries discover a version bearing the operation description or a
matching published code/runtime/architecture snapshot; they never invoke mutable
`$LATEST`. New publication uses optimistic revision/code hash guards. See
[publish version](https://docs.aws.amazon.com/cli/latest/reference/lambda/publish-version.html)
and [version discovery](https://docs.aws.amazon.com/cli/latest/reference/lambda/list-versions-by-function.html).

## Runner version and cluster-skew policy

Evidence pins, not unqualified latest: [AWS2.40.1](https://github.com/aws/aws-cli/releases/tag/2.40.1),
[Azure2.90.0](https://learn.microsoft.com/en-us/cli/azure/release-notes-azure-cli),
[Google Cloud SDK553.0.0](https://docs.cloud.google.com/sdk/docs/release-notes).
Local `--help` checks confirmed gen2 deploy/describe flag asymmetry, explicit
App Engine promotion, Azure ZIP timeout units, container flags, Container Apps
container selection/revision traffic weights, and APIM specification formats.

The observed kubectl1.37.2 is a local evidence version, not a universal cluster
pin. Select the client minor against the configured server and enforce the
[official kubectl version-skew policy](https://kubernetes.io/releases/version-skew-policy/)
(one minor older/newer); an HA mixed-server cluster must satisfy the intersection.
Reject unsupported skew before workload mutation. Helm's observed version4.3.1
is pinned for the authoritative chart command profile; never select random latest.

## Offline validation and remaining rollout gate

`python3 -m unittest discover -s tests/monorepo -p 'test_providers*.py' -v`
covers all17 base target execution paths, serving-failure gates, Lambda ZIP/image
versions/errors/aliases/retries, both Eventarc profiles with an executing local
handler fixture and correlation negatives, Azure container baked-marker failure,
admin production/named-slot exact-master-key metadata and wrong completions,
custom-handler executable metadata, Flex exact bytes/ID/terminal-failure guards,
hostile options, backing-resource aliases, cross-region static-prefix overlap,
account drift, deadlines, and real loopback HTTP with child cleanup on failure.

These are offline command/HTTP conformance tests; no cloud account was mutated.
Actual provider IAM, platform deployment, packaged third-party runtime dependencies,
Azure worker startup, and real Eventarc/Application Insights delivery still need
credentialed staging rollout validation. No offline fake is evidence of cloud
availability, and no provider emits a successful deployment receipt itself.

## Immutable registry transport and private image prerequisites

`CLOUDOPSWORKS_REGISTRIES` is a **protected GitHub environment/repository variable**, not
component configuration. It maps auth references to existing native repositories:

```json
{"prod":{"provider":"gcp","repository":"us-docker.pkg.dev/project/images"}}
```

AWS values are complete ECR repository URIs; GCP values are
`LOCATION-docker.pkg.dev/PROJECT/REPOSITORY` (the component ID is appended);
Azure values are `NAME.azurecr.io/REPOSITORY`. Federation must already grant read
native-resource metadata and push permission. Deployment runtime/node identities
must already have pull permission on that native registry. No registry, role,
network, or landing-zone creation occurs. Map changes affect preview configuration
identity and therefore trigger reconciliation.

Lambda image deployment always discovers the existing function's
`Code.ResolvedImageUri`, verifies that repository's actual account and target
region through `aws ecr describe-repositories`, then promotes there. AWS requires
private ECR in the function's region ([Lambda container image requirements](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)).
The source must be a single image manifest, not an OCI index.

For other OCI targets, an absent map permits **anonymous/public images only**:
`skopeo inspect --no-creds --format '{{.Digest}}' docker://SOURCE@sha256:...`
must prove the exact digest. A workflow GHCR login never establishes Kubernetes
or managed-runtime pull access. Private GHCR therefore requires the protected
native-promotion map, including for Kubernetes previews. Source GHCR access uses
`GH_TOKEN` with `packages:read` (preview publishing also needs write); native
credentials come from the existing federated CLI identity.

Promotion uses temporary mode-0600 auth files, removed on success and failure.
All registry passwords/tokens pass only through stdin to `skopeo login` and are
never argv or diagnostic output. Native tokens are retrieved using
`aws ecr get-login-password --region REGION`, `gcloud auth print-access-token`, or
`az acr login --name NAME --subscription SUB --expose-token --output json`.
The transport is `skopeo copy --all --preserve-digests --authfile FILE
 docker://SOURCE@DIGEST docker://DEST:sha256-HEX`, followed by exact destination
inspection (and native ECR image digest readback). The deployment uses
`DEST@DIGEST`; the original artifact digest/provenance and receipt stay unchanged.
A destination rewriting the manifest fails before workload mutation.
[Skopeo 1.13.3 copy semantics](https://github.com/containers/skopeo/blob/v1.13.3/docs/skopeo-copy.1.md),
[inspection semantics](https://github.com/containers/skopeo/blob/v1.13.3/docs/skopeo-inspect.1.md),
[GCP supported registries](https://docs.cloud.google.com/run/docs/deploying#supported-container-registries-and-images).

App Engine container mode uses a generated fixed `runtime: custom`, `env: flex`
configuration with typed service and health paths, and
`gcloud app deploy ... --image-url GAR_IMAGE@DIGEST --version VERSION --promote`.
The container must listen on App Engine's required port **8080**; other typed
ports fail before registry copy or application mutation. An Artifact Registry
image is required (normally via the protected GCP map). The serving version must
report the exact immutable container image and 100% service allocation before
HTTP readiness succeeds. Installed gcloud 553.0.0 `app deploy --help` confirms
`--image-url` is flexible-only and requires an Artifact Registry hostname;
[official command reference](https://cloud.google.com/sdk/gcloud/reference/app/deploy),
[custom runtime requirements](https://cloud.google.com/appengine/docs/flexible/custom-runtimes/build).

Normal deployment read-only resolution also verifies every configured native
registry before global ownership preflight allows any apply job. The normalized
protected destination (never credentials) participates in `effective-target/v1`
configuration identity: changing a registry triggers a target-changed receipt
reconciliation even when no source component is rebuilt. Apply rechecks the
selected protected mapping against the read-only resolution. Each target's
canonical primary ownership claim supplies the stable concurrency lock; volatile
artifact staging keys remain ownership claims but do not alter that lock.
Beanstalk staging keys are artifact-content-addressed, avoiding an idempotency-key
/configuration-digest cycle during re-resolution.

Native registry authentication references:
[AWS ECR get-login-password](https://docs.aws.amazon.com/cli/latest/reference/ecr/get-login-password.html),
[Azure ACR login/expose-token](https://learn.microsoft.com/en-us/cli/azure/acr#az-acr-login),
[gcloud auth print-access-token](https://docs.cloud.google.com/sdk/gcloud/reference/auth/print-access-token).
