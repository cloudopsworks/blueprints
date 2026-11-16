# Composite-first isolated-slice test plan

This is local regression tooling, not a production runtime or final architecture approval.

1. Lock the new transitive action boundary RED before production edits. Keep the
   existing 24 legacy contract tests as compatibility characterization.
2. Extract exact `actions/github-script@v9` bodies and their environment declarations
   from actual YAML using installed `yq`; execute those bytes with Node's built-in
   test runner and isolated, network-denying toolkit/API/native-tool doubles.
3. Exercise real temporary Git history and installed/local Tronador, not a second
   selector. Cover changed, removed, renamed and configuration-only source changes.
4. Prove descriptor-free transport/archive validation, embedded typed-record links,
   then descriptor-required payload verification. Unsafe outer archives leave no
   extracted files; inner mismatches expose no verified application output.
5. Cover Lambda derived inputs, expired-payload native destroy planning and unlock
   with no artifact/render calls. CLI ownership remains with the Go lane.
6. Report scanner, closure/tag, native-plan and transitive-boundary results separately.
   Doubles are not hosted, cloud, scanner-service or CNI evidence.

Do not delete rejected runtime or migrate the broad graph. The isolated executable
slice must receive independent actual-code Architect then Critic review first.
The complete old graph remains a known rejected baseline, never a permitted fallback.

## Current artifact-authority amendment coverage

Raw artifact metadata is application data, not uploader job/attempt authority.
Exact expected-ID planner endorsements use specific current-attempt writer logs;
failed job evidence is denied for planner success. API responses, signed transfer,
and log streams are finite network-denying doubles with a fixed test clock.

Commands (run from `blueprints/`):

- `node --test tests/monorepo/actions/*.test.mjs`: actual YAML body tests with
  strict API/CLI/tool doubles. No hosted or native packaging success implied.
- `TRONADOR_CLI=/tmp/tronador-v511-composite-first node --test tests/monorepo/actions/real-cli.integration.mjs`:
  actual CLI, disposable Git changed/deleted/renamed/config-only/shared selection,
  real Node24/Go native build+test, and actual Go outer archive validation.
  Mixed function packaging deliberately records the missing Docker/OCI gap:
  both actual package calls fail `container-build-failed`, and no result is emitted.
- `TRONADOR_CLI=/tmp/tronador-v511-composite-first python3 tests/monorepo/actions/test_native_render.py -v`:
  actual Go rendering, locked OpenTofu1.11.4/AWS6.35.0 schema and mock-prior Apply,
  original payload deletion, actual historical artifact-free rendering, selected
  real-provider refresh-disabled destroy-only saved plan. This uses an explicit
  non-deployable renderer ZIP fixture, not fake application packaging evidence.
- `python3 tests/monorepo/test_composite_boundary.py -v`: the complete isolated
  transitive boundary. A green structural boundary is not lifecycle completion.

Known gaps are explicit: hosted caller/job/log canary; real scanner process/network
execution; Docker preview OCI build/invocation; default-host/support-base and tag
lifecycle closure beyond the fixed diagnostic manual caller; historical carry
and recovery-only receipt handling; action-level unlock zero calls. The stage
API-only matrix/DAG now has local actual-body evidence, not hosted attestation. Go unit tests
are separate evidence, never silently counted as action integration coverage.

## Mandatory first-slice gate blockers (not optional follow-up work)

The diagnostic carry-deny path does not satisfy approved historical carry/closure,
recovery-only receipt authority, or action-level unlock zero-call requirements.
These must be implemented and verified before the first-slice actual-code gate
can pass. Same-host DAG/current-matrix local regressions now pass. Scanner RED
regressions were repaired: verified OCI root/config identity precedes fixed native
tar into a private layout directory; pinned image-report correlation and empty
coverage denial pass local fixtures. Native OCI preparation is proven separately;
a successful classifier double is not actual scanner-process evidence.

## Candidate2 regression-first repair chronology

Candidate1 actual-code Architect then Critic rejected the incomplete slice. The test
lane added these assertions **before** authorizing corresponding product repairs:

- `node --test --test-name-pattern='physical payload|aliased descriptors' tests/monorepo/actions/artifact.test.mjs`:
  six passed, one failed because identical main/preview descriptors sharing one
  physical file were rejected with `artifact-file-set`. Contradictory descriptors
  and unexpected physical files remain denied.
- `TRONADOR_CLI=/tmp/tronador-v511-composite-first node --test --test-name-pattern='shared main/preview payload alias' tests/monorepo/actions/real-cli.integration.mjs`:
  two passed, one failed. The existing real BuildPlan/ComponentResult fixtures first
  passed actual Go linked validation; the actual YAML records body then wrongly
  rejected their shared path. This is descriptor/file-set evidence, **not** native
  OCI packaging success.
- `node --test --test-name-pattern='explicit main purpose|artifact purpose|requested main image' tests/monorepo/actions/scanner-correlation.test.mjs`:
  six failed: requested main could silently select preview, missing/unknown purpose
  was accepted, and main non-OCI could silently substitute preview.
- `node --test tests/monorepo/actions/workflow.test.mjs`: one passed, one failed;
  reusable defaults were not empty and source-build permissions were not restricted
  to contents-read. Assertions now express role-specific ceilings.
- `node --test tests/monorepo/actions/native-trivy.test.mjs`: two failed; real legacy
  and typed adapters shared no native Blueprint invocation composite. The test also
  preserves legacy token, filenames, severities, SARIF and failure semantics.

RED output was sent to the implementation lane before each relevant source repair.
Scanner and workflow raw runs were retained locally at
`/tmp/v511-candidate2-{scanner,workflow,native-trivy}-red.txt`; durable orchestration
receipts belong to Main. Exact action bodies remain hash-bound when extraction is
used. New tests do not authorize broader migration or relax outstanding positive
carry, closure, action-level recovery/unlock and artifact-purpose coverage gates.
