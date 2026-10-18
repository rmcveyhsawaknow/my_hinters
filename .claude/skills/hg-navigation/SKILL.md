---
name: hg-navigation
description: Plan safe movement using Chebyshev distance, terrain costs, and the 12-step cap.
---
# Navigate
1. Use `max(abs(dx), abs(dy))` for tile distance.
2. Avoid deep and shallow water unless a bridge makes the route walkable; hills cost 2.
3. Prefer roads (0.5 cost) and compute the cheapest path within at most 12 steps.
4. Re-observe after movement and do not assume unseen map tiles.
CLI: `hglab observe --agent NAME --json`; preview with `hglab tick --agent NAME --role surveyor --dry-run`.
Check: target lies within bounds and path is walkable before proposing `move`.
Example: compare a short hill route with a longer road route by total rounded energy.

## Weather (API 0.26.2)

On a storm day every tile entered costs 1 more energy (2, hills 3, road 1.5): plan half the usual
distance, prefer roads, and save long migrations for the next day. `observe.weather` and the digest
say which day it is; the hints say what tomorrow brings.
