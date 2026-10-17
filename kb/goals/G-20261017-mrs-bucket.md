---
id: G-20261017-mrs-bucket
type: goal
title: 'MotherPail: stores that are never empty'
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- builder
- envoy
- mrs-bucket
links:
- agents/mrs-bucket/persona.md
- agents/mrs-bucket/metrics.yaml
parent: null
success_test: Two farms producing, the factory storehouse receiving berries or wood at least once per
  real day for 14 days, and no teammate run record showing energy below the floor on a wake after she
  gave to them.
score: 0.7
---

Owned by the persona `mrs-bucket`; progress is read from its Pulse (`hglab pulse --agent mrs-bucket`). Any plan that depends on a monument carries a fallback until H-20261017-monument-buildable is settled.
