---
id: H-20261026-navy-opus-every-wake
type: hypothesis
title: 'Fathomark: a model that reasons over the chart every wake builds more per
  wake than the chart''s rules alone'
status: proposed
created: '2026-10-26'
updated: '2026-10-26'
author_runtime: claude-code
roles:
- navy
links:
- agents/navy/metrics.yaml
prediction: Bridges and signs per wake are higher on wakes planned by the model (Opus
  5.5) than on wakes the daily cap hands to the rules.
falsifier: The rules-only wakes build as much or more per wake over the first seven
  days.
prereg_commit: ''
window_start_utc: ''
---

The model sees the whole chart, the works and the pack together and can choose a different work, a better wood source or a sign; the rules take the nearest open work every time.
