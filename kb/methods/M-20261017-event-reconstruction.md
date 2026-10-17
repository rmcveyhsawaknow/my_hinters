---
id: M-20261017-event-reconstruction
type: method
title: Event-sourced world reconstruction
status: proposed
created: 2026-10-17
updated: 2026-10-17
author_runtime: human
roles: [observer, physicist, skeptic]
links: []
---

Replay deduplicated public events to rebuild state, then compare with a contemporaneous `/live/world.json` snapshot. Record schema gaps and checksum both inputs; treat snapshot mismatch as a pipeline self-check, not world evidence.
