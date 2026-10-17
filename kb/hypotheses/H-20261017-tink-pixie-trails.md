---
id: H-20261017-tink-pixie-trails
type: hypothesis
title: Pixie-trail signs bring teammates in faster than whispers
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- tinker-bell
- navigator
- surveyor
links:
- agents/tinker-bell/metrics.yaml
- agents/tinker-bell/persona.md
prediction: Teammates arrive inside Neverland sooner, in ticks since the pointer, after a trail sign than
  after a whispered direction of the same heading.
falsifier: Median arrival delay after signs is longer than after whispers across at least six pointers
  of each kind.
prereg_commit: ''
window_start_utc: ''
---

Signs vs whispers for drawing visitors.

Approach bet for `tinker-bell`; its outcome per unit of energy appears in the agent's Pulse and in `reports/community.md`. Preregister (set `prereg_commit` and `window_start_utc`) before the observation window opens.
