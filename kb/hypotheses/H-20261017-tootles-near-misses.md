---
id: H-20261017-tootles-near-misses
type: hypothesis
title: Tootles arrives after big events more often than chance
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- tootles
- statistician
links:
- agents/tootles/metrics.yaml
- agents/tootles/persona.md
prediction: His near-miss counter (arrival within 60 ticks after a landmark build or confirmation in view)
  exceeds the rate expected from his movement alone, estimated by shuffling event times.
falsifier: The observed count is within the shuffled distribution's central 90%.
prereg_commit: ''
window_start_utc: ''
---

The comic metric, with a null model.

Approach bet for `tootles`; its outcome per unit of energy appears in the agent's Pulse and in `reports/community.md`. Preregister (set `prereg_commit` and `window_start_utc`) before the observation window opens.
