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
