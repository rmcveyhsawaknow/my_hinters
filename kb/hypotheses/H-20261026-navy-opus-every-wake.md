---
id: H-20261026-navy-opus-every-wake
type: hypothesis
title: 'Fathomark: a model that reasons over the chart every wake builds more per
  wake than the chart''s rules alone'
status: proposed
created: '2026-10-26'
updated: '2026-10-27'
author_runtime: claude-code
roles:
- navy
links:
- agents/navy/metrics.yaml
prediction: Bridges and signs per wake are higher on wakes planned by the model (Sonnet
  5.5 from 2026-10-27; Opus 5.5 before) than on wakes the daily cap hands to the rules.
falsifier: The rules-only wakes build as much or more per wake over the first seven
  days.
prereg_commit: ''
window_start_utc: ''
---

The model sees the whole chart, the works and the pack together and can choose a different work, a better wood source or a sign; the rules take the nearest open work every time.

Change before the window opened (2026-10-27): the owner moved Fathomark from Opus 5.5 to the lesser-cost Sonnet 5.5 (`tick_premium`). The id keeps its first name; the comparison is model-planned wakes against rules-planned ones, and each run record names the model that planned it (`thinking.model`), so the Opus wakes of 2026-10-26/27 can be split out.
