---
id: G-20261103-neverland-grows-by-twice-what-stands
type: goal
title: Neverland's Treetop Hideaway grows by twice what stands, with rope ladders and rope bridges
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, surveyor]
links:
  - teams/blueprints/treetop-hideaway.yaml
  - teams/neverland.yaml
  - src/hglab/factory.py
  - tests/test_treetop.py
parent: null
success_test: 'The treetop-hideaway ledger records every step of the six new sections (story-tree, watch-tree, mending-tree, hollow-oak, strays-tree, crows-nest-tree), the old trees'' ten rope ladders and the seven new bridges as done (hglab factory show), the six sign structures stand beside their trees in /live/world.json, and the 71 steps of 2026-11-02 keep their ids and actions (tests/test_treetop.py).'
score: 0
---
The owner's instruction of 2026-11-03: Neverland's Treetop Hideaway grows by 200%. Read as twice what stood added
to it: three treehouses became nine, joined into one hideaway by rope bridges, and every trunk gets a rope ladder,
since walkers in this world have no height and the ladders are what make the decks look reachable.

- Ground: in the world of tick 153234 only two spots inside the ring of riddle signs were still clear of huts, roads
  and the old trees' blocks, the Strays' Tree (77-79,106-108) by Tinkerglow's hut and the Crow's Nest Tree
  (65-67,106-108) under the West Tree. The other four stand in the forest north of the ring: the Story Tree, the
  4x4 hall (70-73,98-101), the Watch Tree (75-77,96-98), the Mending Tree (65-67,100-102) and the Hollow Oak
  (61-63,100-102). West of them the land office's walled lots (G09, F09) leave no room; east of x 77 the ground is
  within two tiles of the Chocolate Factory's campus wall (x 80, y 99), so nothing goes there.
- Rules kept: every trunk on forest with no node, structure, block or lot centre, and none on the ring's rows or
  columns; decks at levels 6 and 7 close nothing and cover no wall, hut, farm or store; every box is at most 64
  cells; each tree has a cabin, its own colours, a ladder per trunk and a sign beside it.
- Ledger: the old trees keep their sections untouched. `ladders: true` on them would hang each ladder straight
  after its trunk and renumber 58 of the 71 steps the ledger names, so their ten ladders are thatch tubes in their
  own sections after their last step, with the same actions the flag makes.
- Bridges: seven new ones (ring, watch, mending, hollow, crow's nest, strays, lookout), wood one cell thick, from one
  railing to another, sagging mid-way, all at level 6 and above and through no cabin.
- Cost: 4,503 blocks in all against 1,468 before; the new work needs 649 wood and 162 fiber. The four builders own
  about 1,500 blocks between them, far under the cap of 4,096 each.

Evidence: `hglab factory check --name treetop-hideaway` (272 steps, no problem against the public world),
`hglab factory show --name treetop-hideaway`, and `tests/test_treetop.py`.
