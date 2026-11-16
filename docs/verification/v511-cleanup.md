# v5.11 bounded cleanup plan

Status: written before source edits; independently reviewed and acknowledged by Main. This is a
cleanup evidence record, not new feature or release authority.

## Scope and exclusions

Inspect the current implementation changes, including untracked authored files:
Blueprints `monorepo-*` workflows, `ci/monorepo`, `cd/monorepo`,
`tests/monorepo`, authoritative Helm chart, ADR/reference/wiki and agent/README
sources; isolated `tronador-cli-v511` components, CLI adapter and modified project/
catalog integration; authored monorepo and Ruby template content. Preserve the
frozen PRD/test-spec/contract and baseline inventory under workspace `.omx`.

Do not modify the six existing reference templates, original `tronador-cli`,
legacy Blueprint CI/CD/Terraform, `.idea`, `.git`, protected version markers,
generated README/schema/corpus copies independently, or orchestration state.
No new dependencies, abstractions, API changes, architectural decisions, feature
expansion or cosmetic formatting sweep. README.md is generated from README.yaml.

## Behavior lock before cleanup

Existing regressions cover source/dependency selection, strict shared JSON and
artifact contracts, rollback/scaffold safety, real language assets, release and
provider failures, receipt convergence, preview trust/isolation/cleanup, and
workflow/chart compatibility. Fresh narrow baseline:

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s blueprints/tests/monorepo -p 'test_*.py'`: 63 tests, PASS, one existing skip.
- `go test ./internal/components ./internal/project ./internal/repos ./internal/cli`
  in isolated CLI: PASS (components/project/repos/cli).

Main reports full Go/vet/race, 85 real template smoke checks, 62 shared corpus
cases, four workflow actionlint checks and 1,466-byte identical default chart
render. These are supporting prior evidence, not cleanup-agent rerun claims.
Any selected edit must already have targeted coverage; uncovered or behavior-
ambiguous changes are deferred upward rather than adding behavior in this pass.

## Fallback inventory and classification gate

| Surface | Preliminary classification | Preservation / escalation |
|---|---|---|
| Go selection missing/zero/unavailable baseline; preview baseline unknown/divergent | Grounded fail-safe: select all, not false no-op | Retain; inspect regression coverage before any simplification |
| Release baseline catch of old non-monorepo releases | Grounded compatibility: only skip releases lacking monorepo manifest; corrupt manifest rethrows | Retain release lineage and corruption evidence |
| GitHub 404 and allowlisted signed artifact redirect | Grounded external API boundary | Retain caller-specific absence semantics, no Authorization forwarding |
| Provider polling and bounded network/JSON response interpretation | Grounded external/version boundary when failures remain explicit | Verify timeout/error propagation; escalate any ambiguous masking |
| Deploy/preview broad catches and CLI top-level redaction | Grounded fail-safe when typed failure receipt/state is saved and failure re-raised; log redaction intentional | Preserve partial siblings, retry state and secret handling; inspect each catch |
| JSON-schema anyOf branch catch | Grounded validator algorithm: failing alternatives do not imply success | Retain failure when all alternatives fail |
| Scaffold absent startup build marker and Rails process-local random secret | Grounded documented development/stateless boundary | Preserve immutable startup capture, explicit Rails warning and operator-key limitation |
| Smoke macOS Maven PATH adjustment | Grounded local tooling compatibility | Retain wrapper bytes, no production execution-path change |

No masking fallback is yet established. Search fallback/skip/default/exception
sites and trace surrounding control flow/tests; classify any additional finding
before changing it. Cross-layer ambiguity goes to Main, not nested ralplan.

## Ordered passes

1. **Dead code:** find unreachable branches, unused locals/imports/helpers and debug
   residue; delete only proven redundancy. Preserve platform-specific rename and
   embedded scaffold variants.
2. **Duplication:** inspect repeated local branches; use existing utilities only
   when equivalent evaluation/order/errors are obvious. Keep distinct native
   provider contracts and frozen cross-language wire copies distinct.
3. **Naming/error handling:** only clarify touched implementation structure where
   exact outputs, signatures, error behavior and side-effect ordering remain.
   Keep comments documenting trust, fallback and non-obvious decisions.
4. **Tests:** rerun narrow existing regressions after every applied smell pass;
   inspect edge coverage, defer gaps to Main. No test weakening/removal or new
   tests in this behavior-preserving simplifier lane.

A pass may conclude no warranted safe change; do not manufacture churn. Record
exact changed paths/lines, equivalence reasoning and fresh checks. Run Go vet/
gofmt diagnostics for modified Go; Python compilation/static checks and relevant
unittests for modified Python; actionlint for workflow edits; chart compatibility
for Helm edits. Final regression rerun covers all affected boundaries.

## Review separation and exit condition

Cleanup writer is this delegated simplifier. Main independently reviews this plan
and acknowledges before source cleanup starts; final code-reviewer and architect
lanes are independent. Stop once fallback gate and passes are completed/deferred,
checks are fresh, exact limits are reported and no temporary artifacts remain.
Docker/OCI execution, hosted Actions, live cloud/native registries and real CNI
probes are unavailable/not executed and must never be claimed as passed.

## Completed pass evidence

Main reviewed and acknowledged the plan before any source edit. The cleanup
writer did not act as the final reviewer; independent code/architecture review
remains with Main's separate lanes.

- **Fallback gate:** traced the listed selection, release, GitHub redirect/absence,
  schema-union, polling, partial preview and redacted failure boundaries. No
  established masking fallback was changed or hidden. Native registry no-map
  behavior is also grounded fail-closed: anonymous digest-verified access is
  required, and missing private access fails rather than assuming credentials.
  Unsupported-platform no-replace scaffolding explicitly fails. Development
  startup-marker absence returns no provenance; serving identity checks still
  reject it. Existing regressions preserve primary and adversarial failure paths.
- **Pass 1 (dead code), applied:** removed the repeated `opts.Plan == nil` package
  branch from `internal/components/operations.go:232`. Entry guard at line 91
  rejects a missing plan before any process. `opts` is a value parameter and
  `opts.Plan` is never reassigned, so the removed branch was unreachable; outputs,
  errors, interfaces, callbacks and side-effect order are unchanged.
- **Pass 2 (duplication), inspected:** no further warranted safe edit. Provider
  differences, embedded language variants and frozen contract mirrors are
  intentional boundaries, not consolidation candidates for this pass.
- **Pass 3 (naming/errors), inspected:** preserved public symbols/imported module
  names and existing error handling; no broad style/formatting or ternary rewrite.
- **Pass 4 (tests), verified:** no tests added, weakened or removed. Existing
  `TestPackageRequiresPlanBeforeProcesses` and
  `TestPackageEmitsOnlySelectedOwnerWithDependency` cover rejection before
  execution, selected-owner packaging and no-process dry-run. Package/plan tests
  passed fresh before and after the deletion.
- **UI/design:** N/A; no product UI is in this cleanup scope.

### Fresh validation after source cleanup

Tool versions: Go 1.27.4 darwin/arm64, Python 3.13.18, actionlint 1.7.12,
Helm v4.3.1. Commands were local and did not publish or deploy.

| Check | Result |
|---|---|
| Isolated CLI existing package/plan tests (`-count=1`) | PASS before and after; exact command below |
| `gofmt -l internal/components/operations.go` | Empty; PASS |
| Isolated CLI `go test ./...` | PASS |
| Isolated CLI `go vet ./...` | PASS; static analysis/type diagnostics |
| Isolated CLI `go test -race ./internal/components ./internal/project ./internal/repos ./internal/cli` | PASS |
| Isolated CLI `go build -trimpath -o /tmp/tronador-v511-cleanup .` | PASS |
| `TRONADOR_TEST_BINARY=/tmp/tronador-v511-cleanup PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s blueprints/tests/monorepo -p 'test_*.py'` | 63 tests PASS, no skips; includes 62-case corpus and source-CLI incremental preview integration |
| `actionlint blueprints/.github/workflows/monorepo-*.yml` and each new template's `.github/workflows/*.yml` | All 12 workflow files PASS |
| In-memory Python compile/AST parse of all 16 runtime modules | PASS; no cache artifacts written |
| `helm template compatibility blueprints/kubernetes/helm/charts` compared with locked fixture | Byte-identical, 1,466 bytes |
| Frozen mirror bytes | Three schema pairs and all 78 corpus files identical |
| Baseline legacy Blueprint hash comparison | 236 files, zero differences |
| `git diff --check` in Blueprints and isolated CLI | PASS |

The exact focused regression command (isolated CLI working directory):

```sh
go test ./internal/components -run 'Test(Package|.*Package.*|.*Plan.*)' -count=1
```

Only product-source delta from this helper is the three-line branch deletion;
the other changed file is this requested cleanup plan/evidence record. A pre-edit
hash inventory covered 417 existing changed/untracked authored files, and the
post-edit comparison found only `operations.go` changed before this record was
appended. No six-template/original-CLI/legacy/state writes were made.

**Remaining limits:** no new dedicated security scanner ran; `go vet` and existing
adversarial tests are static/regression evidence, not a security audit. The 85
real template smoke checks are Main's prior evidence, not rerun by this helper,
because scaffold/template assets were unchanged. Docker builds, Linux native
preparation, hosted Actions, live cloud/registries and real CNI enforcement remain
rollout gates. No cleanup-specific behavior uncertainty remains. Source cleanup
is finished; independent final reviewer/architect review is the handoff boundary.

## Final post-review repair cleanup: delta plan

Scope: stable review repairs only—numeric Node container identity; strict Go
OpenAPI parsing and data-only CLI/root-hook bypass, bounded Python validator hook;
scoped private GHCR readback and draft publication state; all-active preview
groups and durable spec sidecars/exact originating run references; sole CLI
maxParallel authority; safe structured diagnostics/typed failure reports; pinned
CLI composite and affected workflows. Preserve the previous three-line dead-code
removal. Writer-owned guide/wiki/CLI usage documentation is excluded.

This delta plan precedes any proposed product edit. Default outcome is a product
no-op: inspect new guards/fallbacks and ordered passes (1 dead code, 2 duplication,
3 naming/errors, 4 existing regression verification), without cosmetic churn,
dependencies, new tests/APIs, frozen mirror drift, state writes or delegation.
Any warranted behavior-proven micro-edit will first be described to Main and wait
for Main's independent ACK; uncertain behavior goes upward unchanged.

Fallback resolution gate: retain scoped registry credentials/anonymous-public
proof, authenticated draft discovery plus exact readback, bounded data-only
OpenAPI subprocess failure, missing preview baseline/spec fail-closed behavior,
and redacted typed diagnostics when they preserve the repaired trust boundary.
Classify any evidence-masking or ambiguous branch before proposing a change.

Behavior lock: run current existing components/CLI regressions before edits,
then Go vet/gofmt diagnostics, fresh source-built `/tmp/tronador-v511` Python
suite (expected 74 tests), 12-workflow actionlint, 83 shared cases and all 120
corpus mirror files. Main owns fresh full Go/smoke evidence and final independent
APPROVE/CLEAR gates. No Docker, hosted Actions, live cloud or CNI claim is added.

### Confirmed test-harness hygiene micro-cleanup (specific Main ACK)

Before editing, reproduced standalone
`test_release.ReleaseTests.test_failed_attempt_retries_even_without_source_builds`
in an isolated temporary cwd with CLOUDOPSWORKS_DIAGNOSTICS unset: test passed but
created the same 276-byte fixture convergence event as the ignored Blueprint
worktree artifact. Unlike the other event-emitting test modules, `test_release`
did not import existing `diagnostic_support`; full-suite discovery masked that
standalone harness gap. Main specifically acknowledged adding that existing
harness import. Apply only `import diagnostic_support` to `test_release.py`;
keep runtime defaults and all test assertions unchanged. Rerun standalone in a
fresh temporary cwd with no diagnostics override and require no local artifact,
then full source-built suite. Delete only the identified fixture event and its
empty generated directory; no broad cleanup. This is an existing-test isolation
repair, not an added regression or product behavior change.

### Final repair-pass outcome and verification

Main independently acknowledged the delta plan and the exact harness import
before editing. Product-source cleanup is a **no-op**: no runtime, workflow,
scaffold, schema or corpus changes were warranted. New bounded OpenAPI validation,
scoped GHCR anonymous/authenticated reads, verified draft discovery, all-active
preview accounting/spec source revalidation, CLI-owned concurrency and typed
redacted diagnostics are grounded boundaries, not fallback code to delete.

Ordered passes completed: dead-code and duplication scans found no additional
behavior-proven deletion; naming/error handling retained trust guards and public
interfaces; the test pass repaired only standalone harness isolation using the
existing helper. `blueprints/tests/monorepo/test_release.py:1` now imports
`diagnostic_support`, matching the other event-emitting test modules. Assertions,
product behavior and default diagnostics layout are unchanged. The prior Go
three-line deadguard removal remains intact. UI/design findings: N/A.

Fresh checks from this final pass:

- Isolated CLI `go test ./internal/components ./internal/cli -count=1`: PASS.
- Isolated CLI `go vet ./internal/components ./internal/cli`: PASS.
- `gofmt -l` on component Go source/tests and CLI components/root files: empty.
- Isolated CLI `go build -trimpath -o /tmp/tronador-v511 .`: PASS; this fresh binary
  drove Python validation. Binary retained for Main's subsequent smoke checks.
- `env -u CLOUDOPSWORKS_DIAGNOSTICS TRONADOR_TEST_BINARY=/tmp/tronador-v511 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/monorepo -p 'test_*.py'`
  from Blueprints: **74 tests PASS, no skips**. No worktree diagnostics directory
  created, including with the diagnostics override explicitly unset.
- Standalone retry-unresolved release test in a temporary cwd with diagnostics
  override unset: PASS before/after; generated local diagnostics before, none
  after. Removed only the confirmed 276-byte fixture event and empty ignored
  Blueprint directory. No CLI/Blueprint diagnostic directories remain.
- All 12 central/new-template workflows: actionlint PASS.
- Go/Python shared corpus: **83 cases, all 120 mirror files byte-identical**;
  all three schema mirror pairs byte-identical.
- In-memory syntax/AST checks: all 17 runtime Python modules PASS; modified
  `test_release.py` compiles. Blueprint and isolated CLI diff checks PASS.
- Product no-op verification: 221 repair-source/asset/workflow hashes unchanged.

Changed in this final pass: this requested evidence record and the one-line
existing-test harness import only. No new dependencies, tests, APIs, runtime
fallbacks or writer-owned documentation were added/changed. No source behavior
uncertainty or architectural escalation remains from this cleanup scan. Dedicated
security scan, Docker/native preparation, hosted Actions, live cloud/registries and
real CNI remain unexecuted limits. Main owns fresh full-Go/85-smoke verification
and independent final code/architecture review; this helper does not claim those
pending gates complete.

## A6 diagnostic/preview delta: bounded no-op plan

Before any edit, scope this final scan only to strict diagnostic namespace/
provider fields, trusted artifact identity tuples and GitHub UI links; preview
artifact-link capture and readiness/owned-namespace events; guarded cleanup
`deleted`/`noop` outcomes with closed-state persistence; and their existing
`test_review_repairs`/`test_preview` regressions (75 total suite tests). Main
acknowledges default product no-op. No runtime/test edit is authorized without a
specific newly proposed case and independent ACK. Preserve schema/corpus bytes,
trust guards, runtime outputs and prior cleanup; no full Go/smoke rerun for this
Python-only delta. Run source-built CLI-backed suite, syntax/static checks,
mirror checks and no-worktree-artifact verification; append observed results.

### A6 outcome: product no-op

No additional runtime/test edit proposed or applied. Fallback/dead-code/
duplication/naming scans retain strict diagnostic allowlisting, exact trusted
artifact tuple/link matching, readiness events after durable state, and cleanup
outcomes after ownership/PR/UID guards and closed-state persistence. These are
grounded evidence boundaries, not masking fallbacks. Existing adversarial link,
secret-redaction, cleanup race and repeat-safe regressions remain intact.

Fresh validation: trusted `/tmp/tronador-v511-final` with diagnostics override
explicitly unset drove **75 Python tests PASS, no skips** from Blueprints; no
worktree diagnostic artifacts appeared. Both A6 runtime modules and both touched
test modules passed in-memory syntax/AST checks. All 12 workflows passed
actionlint; Blueprint diff check passed. **83 shared cases / 120 corpus mirror
files** and all three schema pairs remain byte-identical. Only this requested
cleanup evidence record changed in this A6 helper pass. No full Go/smoke rerun
was needed for this Python-only delta; no new tests, dependencies, APIs, state
writes or product changes. Remaining external/security verification limits are
unchanged. Independent reviewers own final approval; cleanup is idle.
