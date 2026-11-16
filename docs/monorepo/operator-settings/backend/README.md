# Organization/team Terraform state settings

These inactive YAML examples illustrate the **value of `DEPLOYMENT_STATE_CONF`**,
provided by org/team variables and secrets as in the language templates. They are
platform operator documentation, not application-repository configuration.

- [S3](s3.yaml), [GCS](gcs.yaml), [Azure](azure.yaml): choose one backend and replace
  placeholders with existing operator-approved state resources and auth bindings.
- Central jobs read `vars.DEPLOYMENT_STATE_CONF` first, with optional
  `secrets.DEPLOYMENT_STATE_CONF` compatibility fallback. Do not commit real values
  or copy these files into application `.cloudopsworks/`.
- `auth_ref` selects an existing entry in the same protected `CLOUDOPSWORKS_AUTH`
  map. Workload and backend credentials may differ; adding components does not
  require a new backend file, map or credential setup.
- Generated private native backend/cache/plan files are ephemeral execution data,
  not a second config source. Never upload them as artifacts or diagnostics.

The CLI normalizes bounded YAML from stdin; it does not discover a repository
backend file. Historical recovery preserves the verified old backend address and
identity, regardless of current application YAML. See the
[runbook](../../rollout.md#independent-workload-and-backend-authentication) for
legacy recovery limits and [configuration ownership](../../guide.md#configuration-ownership).
