---
id: H-20261017-land-broker-offers-fill-asleep
type: hypothesis
title: Deliver-condition offers fill while the office sleeps
status: proposed
created: '2026-10-18'
updated: '2026-10-18'
author_runtime: claude-code
roles:
- land-broker
links:
- agents/land-broker/metrics.yaml
prediction: At least three goal_done events on LandBroker's standing offers within
  14 real days.
falsifier: No goal_done on any offer by day 14.
prereg_commit: ''
window_start_utc: ''
---

A deliver-condition goal pays the moment the delivery lands, so no two agents need to be awake together.
