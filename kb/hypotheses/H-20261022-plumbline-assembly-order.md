---
id: H-20261022-plumbline-assembly-order
type: hypothesis
title: Openings first saves material
status: proposed
created: '2026-10-23'
updated: '2026-10-23'
author_runtime: claude-code
roles:
- plumbline
links:
- agents/plumbline/metrics.yaml
prediction: Builds that place doors and windows before walls use fewer blocks per
  closed tile than builds that cut openings later.
falsifier: No difference in blocks per tile between the two orders across ten observed
  builds.
prereg_commit: ''
window_start_utc: ''
---

Approach bet filed from the hg-new-agent interview.
