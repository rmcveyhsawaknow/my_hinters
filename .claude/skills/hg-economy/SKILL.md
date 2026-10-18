---
name: hg-economy
description: Choose sustainable gathering, construction, and storehouse transfers.
---
# Manage resources
1. Check inventory capacity, node size/regeneration, energy, and existing structures.
2. Build hut first when feasible, then grass farm, useful roads, and shared storage.
3. Gather at most five units per action; do not strip a node or exceed sustainable yield.
4. Check storehouse policy before taking; transfer peer resources directly with `give`.
CLI: preview with `hglab tick --agent NAME --role builder --dry-run`.
Check: blueprint materials and terrain match the offline API table.
Example: use a farm's 3 berries/30 ticks as a steady flow, not an unlimited harvest.

## Farms, storehouses and trade offers (API 0.22.0)

Only your three oldest farms grow berries; a fourth stands idle, so stop at three and keep
them emptied (`take` at the farm). `give` works into any storehouse, yours or not; a
storehouse's `policy` only limits who may `take`. To trade with agents who are not online when
you are, build a `private` storehouse and post a goal with a `deliver` condition into it
("10 wood for 5 stone"): it pays out the moment the delivery lands.

## Repair, decay, harvest and weather (API 0.26.2)

Carry a little stone and wood: `repair x,y` (3 energy) mends 20 hp of your own or your faction's
structure for one unit (stone for roads, walls, towers and monuments; wood for the rest), and damage
from hits or decay never heals by itself. Take berries from your farms before they reach 30: a full
farm grows nothing. Ruins (caches with `ruin` set) and dropped caches are open to anyone: take what
fits. Plan by the day's `season` and `weather`: gather fiber and berries on rain days, stock berries
before winter (wild berries do not regrow then), and keep walks short on storm days.
