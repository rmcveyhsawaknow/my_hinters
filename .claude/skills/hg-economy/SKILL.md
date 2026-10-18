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
