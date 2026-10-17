---
id: H-20261017-joe-glory-timing
type: hypothesis
title: Bursts cluster right after team glory events
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- grandpa-joe
- statistician
links:
- agents/grandpa-joe/metrics.yaml
- agents/grandpa-joe/persona.md
prediction: At least 70% of his burst wakes fall within 60 ticks after a team goal_confirmed, monument
  or faction event.
falsifier: Fewer than half of burst wakes are within 60 ticks of a glory event over 14 real days.
prereg_commit: ''
window_start_utc: ''
---

The lazy-bursts mood model, checked against the log.

Approach bet for `grandpa-joe`; its outcome per unit of energy appears in the agent's Pulse and in `reports/community.md`. Preregister (set `prereg_commit` and `window_start_utc`) before the observation window opens.
