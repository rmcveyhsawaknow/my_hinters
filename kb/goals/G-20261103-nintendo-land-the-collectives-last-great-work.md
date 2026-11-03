---
id: G-20261103-nintendo-land-the-collectives-last-great-work
type: goal
title: Nintendo Land, the collective's last great work
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, surveyor]
links:
  - teams/blueprints/nintendo-land.yaml
  - tests/test_nintendo_land.py
  - teams/chocolate-factory.yaml
  - teams/atelier.yaml
  - teams/exchange.yaml
  - teams/neverland.yaml
parent: null
success_test: 'The nintendo-land ledger records every one of its 1,118 steps as done (hglab factory progress --name nintendo-land), hglab factory check --name nintendo-land reports no problem against the public world, and the 36 sign structures stand beside their buildings in /live/world.json.'
score: 0
---
The owner's instruction of 2026-11-03: plan a large Nintendo-themed area for every agent and team to build once
every other themed area (the Chocolate Factory, the New York replicas, Neverland's hideaway) is complete. The design
is inspired by Nintendo's worlds and built in our own words and shapes: no logos and no quoted text, only the names
of places and things, and every sign written fresh.

- Ground: the open north of the island, x 55-94, y 20-39, the 32 lots F02-NE to J03-SW, held by contract with the
  land office (no deed to wait on). The survey of tick 153228 found grass, a sand band, forest in the south-west, the
  south-east and the north-east corner, about two hundred wood, fiber and berry nodes, no stone or ore node and no
  resident's building. The office's claim signs on the lot centres keep their tiles: no block below level 6 stands on
  one. Lagalong's roads and Sheafwell's walls on the site are clear of every step.
- Content: 36 sections in eleven styles across ten districts. The Mushroom Kingdom has the castle with its keep, a
  giant mushroom whose red cap is four tubes, the first course with floating blocks, warp pipes, a flagpole and the
  goal fort. Then come the Kart Circuit, Dream Land, the Pokemon village, the History Walk of four pavilions (1889,
  1980, 1983, 1989) leading to the Nintendo Museum at the heart, Inkopolis, the animal village, Hyrule's woods, the
  sands of Zebes with a gunship hovering on struts, and the Kong jungle of treehouses, rope bridges and a barrel
  tower. Every section has a sign beside it; lanes at least a tile wide part the buildings and every door opens onto
  open ground.
- Cost (hglab factory show --name nintendo-land): 1,118 steps and 15,556 blocks, 1,328 of them in surveyed plinths.
  That is 2,871 stone, 966 wood and 345 fiber items to gather, and no ore. Sections and lawns cover 406 of the 800
  tiles. Every box is at most 160 cells, so a pack pays for any step, and builders carry each step's material there
  (`commute`). At 4,096 blocks a builder, the land needs at least four builders' full allowance.
- Who builds it: the last entry of every team's `next_blueprint`. The factory crew comes after Lower Manhattan,
  Midtown, Central Park and Uptown; the office's hands after Central Park and Uptown; Plumbline after Uptown; and
  Neverland's builders after the Treetop Hideaway.

Evidence: `hglab factory check --name nintendo-land` (no problems against the world of tick 153228),
`hglab factory show --name nintendo-land`, tests/test_nintendo_land.py, and later the ledger and the sign structures
in `/live/world.json`.
