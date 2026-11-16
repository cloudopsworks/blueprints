# Blueprint repository guidance

@AGENTS.md

Use AGENTS.md as the shared operating contract. For schema-v2 application work,
read `docs/monorepo/guide.md`, the ADRs and `docs/monorepo/rollout.md` first.
Keep YAML-first README generation, authoritative Helm chart ownership and
source-build/deployment credential boundaries intact. Do not treat local mocks
or an implementation branch as a published release or live-cloud validation.
