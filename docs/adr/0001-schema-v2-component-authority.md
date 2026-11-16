# ADR 0001: One typed component model

> Historical initial design. Conflicting configuration/execution claims are superseded by [ADR 0005](0005-yaml-gitflow-iac-revision.md); not current provider capability proof.

- Status: accepted for the v5.11 implementation
- Scope: new monorepo and Ruby templates; existing templates remain unchanged

## Decision

Tronador owns YAML loading, configuration normalization, change selection,
scaffolding and local build/test/package execution. Blueprints consumes validated
`cloudopsworks.io/v1` JSON records; it does not implement a second YAML resolver.

The source registry is `.cloudopsworks/cloudopsworks-ci.yaml` with
`schemaVersion: 2`. Target and preview-policy files are referenced relative to
`.cloudopsworks/`. A component declares an ID, safe source root, exact runtime,
typed build profile, package, HTTP workload or handler contract, preview projection,
dependencies, watches and target bindings. Arbitrary shell commands are not configuration.

The CLI embeds the schema and seven language scaffolds plus the Rails flavor.
`add` uses a locked, rollback-safe source/registry/label transaction; `new` creates a
fresh standalone repository layout. A sole Ruby component may own root `.`;
monorepo component roots cannot overlap. Invalid YAML, aliases, duplicate keys,
unknown fields, unsafe paths and symlink ancestors fail before project execution.

## Consequences

- Go and Python validators share a byte-identical schema and conformance corpus.
- Every matrix owner builds/tests its topological dependency closure. Conflicting
  exact tool versions within a closure fail before executing source.
- Dry-run and validation do not execute generators, scripts, installers or network calls.
- New template operations use Tronador, not Makefiles.
- Legacy configurations stay on legacy commands; there is no implicit migration.

See [configuration and CLI usage](../monorepo/guide.md).
