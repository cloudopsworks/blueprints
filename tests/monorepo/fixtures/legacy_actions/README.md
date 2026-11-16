# Legacy compatibility fixtures

Captured locally on 2026-11-12, before additive v5.11 action changes. These are
historical observations, not proposed component-mode behavior.

- `provenance.yaml` records the Blueprint revision and original action SHA-256s.
- JavaScript files contain exact embedded action bodies, with one provenance
  comment prepended. The test harness supplies offline GitHub/core doubles; no
  credentials, network calls, provider tools, or checkout code are executed.
- `action-defaults.yaml` retains input required/default fields and output values.
- `reference-workflows.yaml` retains event filters, job names, and job guards for
  all six original templates, with each repository revision and workflow SHA-256.
  Tests use these captured semantics without requiring sibling repositories.

Run from the Blueprint repository:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/monorepo -p test_legacy_action_contracts.py -v
```

Node runs the historical scripts; the existing Mike Farah `yq` v4 CLI parses
YAML. Missing tools are reported as skipped tests, not successful coverage.
These checks do not execute GitHub Actions expressions, Git, Terragrunt, cloud
providers, or deployments. The CLI lane's Go differential tests own classifier
port equivalence. These fixtures independently document legacy quirks, including
support match errors, string/boolean `enabled` distinctions, and preview's absent
unlock/apply guard; the latter is a defect, not permission to reuse it unchanged.

Intentional additive refactors may replace literal defaults with expressions.
Update assertions only with evidence that the ordinary legacy call still has
the same behavior; retain historical fixtures as the comparison baseline.
