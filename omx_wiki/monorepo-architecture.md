---
title: "Monorepo Architecture"
tags: ["monorepo", "v511", "architecture"]
created: 2026-11-12T20:41:20.508Z
updated: 2026-11-13T19:33:06.108Z
sources: []
links: ["release-convergence.md", "kubernetes-previews.md", "tronador-components.md", "connected-delivery.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Monorepo Architecture

Blueprints owns central orchestration; Tronador owns the sole typed YAML authority,
affected/closure selection, scaffold generation and actual language build/test.
Seven language profiles plus Rails are in scope; source assets alone do not prove
complete lifecycle execution. One repository version, GitFlow defaults and familiar
cd.deployments are retained. Registry target IDs bind
vars/inputs-ENV.yaml monorepo.targets; no external JSON target tree.

The accepted [[connected-delivery]] design separates origin CI from one automatic
native delivery continuation. Central implementation and hosted/provider activation
remain gated; design approval is not deployment evidence.

See [guide](../docs/monorepo/guide.md), [[tronador-components]],
[[release-convergence]] and [[kubernetes-previews]].
