---
title: "Release Convergence"
tags: ["monorepo", "release", "receipts"]
created: 2026-11-12T20:41:20.679Z
updated: 2026-11-13T19:33:06.108Z
sources: []
links: ["monorepo-architecture.md", "cloud-targets.md", "connected-delivery.md"]
category: pattern
confidence: medium
schemaVersion: 1
---

# Release Convergence

One repository version identifies the release. Only affected sources rebuild;
carried artifacts preserve their original build provenance. Target/config-only
changes can reconcile without pretending new source builds occurred.

The required contract gates publication and workload/preview mutation on completed
current-policy scans, including carried artifacts. Central implementation and
activation remain gated; this is not a claim that normal delivery is complete.
Findings/error/unsupported/pending are not success.
Historical verified state handles/native backend locks guard destroy/unlock; no
current-YAML fallback after source removal and no raw plan/state uploads.

See [[connected-delivery]] for the accepted scan-before-stage ordering and native
all-jobs recovery, [rollout](../docs/monorepo/rollout.md), [[cloud-targets]] and
[[rollout-verification]].
