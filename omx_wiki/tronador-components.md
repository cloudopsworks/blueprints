---
title: "Tronador Components"
tags: ["cli", "scaffold", "ruby", "rails"]
created: 2026-11-12T20:41:21.023Z
updated: 2026-11-12T20:58:50.614Z
sources: []
links: ["monorepo-architecture.md", "rollout-verification.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Tronador Components

Use components validate/list/lifecycle/plan for typed inspection and classification;
add/new for real source generation; build/test/package for actual unprivileged source
execution. All human pipeline configuration is YAML. Settings maps normalize bounded
YAML on stdin; schemas/wire JSON are generated internal contracts.

Adding components preserves custom labels and generates targets: []; bind existing
environment targets in YAML without workflow or credential changes. Rails uses
--language ruby --framework rails and standalone new requires a fresh destination.
No Makefile or automatic commit/push/tag/deploy.

See [commands](../docs/monorepo/tronador-design.md), [[monorepo-architecture]] and
[[rollout-verification]].
