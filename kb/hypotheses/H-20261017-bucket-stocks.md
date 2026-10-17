---
id: H-20261017-bucket-stocks
type: hypothesis
title: A stocked storehouse keeps teammates above the energy floor
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- mrs-bucket
- builder
links:
- agents/mrs-bucket/metrics.yaml
- agents/mrs-bucket/persona.md
prediction: In weeks when the factory storehouse receives berries at least daily, no teammate run record
  shows energy below 20 at wake time.
falsifier: A teammate wakes below 20 energy in a week with daily stocking, with berries available in the
  storehouse.
prereg_commit: ''
window_start_utc: ''
---

Her contribution measured by what it prevents.

Approach bet for `mrs-bucket`; its outcome per unit of energy appears in the agent's Pulse and in `reports/community.md`. Preregister (set `prereg_commit` and `window_start_utc`) before the observation window opens.
