---
id: G-20261017-wonka-tickets
type: goal
title: 'Fudgewright: five golden tickets hidden in a walled vault and settled honestly'
created: '2026-10-17'
updated: '2026-10-31'
author_runtime: claude-code
status: proposed
roles:
- navigator
- broker
- wonka
links:
- agents/wonka/persona.md
- agents/wonka/metrics.yaml
- src/hglab/tickets.py
parent: null
success_test: Five goals titled 'Golden Ticket N of 5' posted with escrowed ore, each a yellow square in one
  strongroom of the walled vault at (93,84)-(95,88), each confirmed by its own deliver condition when a peer who
  broke in gives one berry into that strongroom's storehouse; the wall is mended and the square moved before the
  next; no collective member ever claims one.
score: 0.8
---

Owned by the persona `wonka`; progress is read from its Pulse (`hglab pulse --agent wonka`). Any plan that depends on a monument carries a fallback until H-20261017-monument-buildable is settled.

The mechanic changed on 2026-10-31 at the owner's brief: from riddle signs and whispered words to a random yellow square in a walled grid of strongrooms that a seeker must break into (`knobs.tickets`, `hglab.tickets`).
