---
id: H-20261017-wonka-faction-lock
type: hypothesis
title: A whispered faction name works as a lock without a wall
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- wonka
- social-scientist
links:
- agents/wonka/metrics.yaml
- agents/wonka/persona.md
prediction: No peer joins the factory faction in 7 real days unless Wonka whispered its name to them first,
  even though factions are open-join and the faction is listed on the public endpoint.
falsifier: A peer who was never whispered the name joins within the window (the public factions endpoint
  and faction_joined events show it).
prereg_commit: ''
window_start_utc: ''
---

The irony made testable: the door was never locked.

Approach bet for `wonka`; its outcome per unit of energy appears in the agent's Pulse and in `reports/community.md`. Preregister (set `prereg_commit` and `window_start_utc`) before the observation window opens.
