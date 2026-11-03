---
id: G-20261103-uptown-the-third-replica-north-of-central-park
type: goal
title: Uptown, the third New York replica, north of Central Park
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, surveyor]
links:
  - teams/blueprints/uptown.yaml
  - config/plots.yaml
  - tests/test_uptown.py
  - teams/blueprints/central-park.yaml
  - teams/blueprints/midtown.yaml
parent: null
success_test: 'Plumbline holds the land office deeds for the ten lots D03-NW, D03-NE, D03-SW, D03-SE, E03-NW, E03-NE, E03-SW, E03-SE, F03-NW and F03-SW (site requests nyc-uptown-west, then nyc-uptown-east), the uptown ledger records every step done (hglab factory progress --name uptown), and the sixteen sign structures stand beside their buildings in /live/world.json.'
score: 0
---
The owner's instruction of 2026-11-03: the larger New York replica continues north of Central Park with Uptown, on
the ten lots x 30-54, y 30-39 (plots D03, E03, F03), bought from the land office in two segments after Central Park's.

- Ground (survey of tick 153228): forest with wood nodes and sand by the sea in the west, a sand valley with berry and
  fiber nodes on its western grass in the middle, grass rising toward the shore in the east; no stone or ore node, no
  resident's holding, the office's claim sign on every lot's centre and a pocket of shallow water at (43-44, 29-30).
  No footprint closes a node, a claim sign, a street or the water; only one section, the Cloisters, needs a plinth.
- Content: sixteen sections. In the city Uptown wraps the park; the glass has ground only north of it, so the wrap is
  unfolded: the West Side on the west lots (the Cloisters, Grant's Tomb, Riverside Church, the Natural History Museum
  and its Rose Center west of Broadway; Columbia's Low Library and St John the Divine east of it), Harlem in the middle
  (the three rows of Strivers' Row, the Apollo on 125th Street, Morningside Park, the Harlem Meer), the East Side on
  the east lots (the Harlem-125th Street station under the Park Avenue viaduct, the Guggenheim, Gracie Mansion).
  Low Library stands north of 125th Street, where the forest leaves room; the Dakota and Lincoln Center found none.
- Streets: Broadway at x 33, Fifth Avenue at x 43 (from y 31, off the water), 125th Street at y 34, 110th Street at
  y 39. Riverside Church's tower is the tallest at level 13, under Midtown's Empire State Building.
- Cost (hglab factory show --name uptown): 268 steps, 3,783 blocks; 873 stone, 132 wood, 29 fiber, no ore. Every box
  is at most 160 cells, so a pack pays for any step.

Evidence: `hglab factory check --name uptown` (no problems against the world of tick 153403 and the fixture world),
`hglab factory show --name uptown`, tests/test_uptown.py, and the deeds and sign structures in `/live/world.json`.
