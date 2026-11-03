---
id: G-20261103-the-factory-grows-by-twice-what-stood
type: goal
title: The factory grows by twice what stood, in buildings and in ground
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, surveyor]
links:
  - teams/blueprints/chocolate-factory.yaml
  - teams/chocolate-factory.yaml
  - teams/exchange.yaml
  - src/hglab/factory.py
  - tests/test_east_works.py
parent: null
success_test: 'The chocolate-factory ledger records every step of the eighteen East Works sections, their river branches, tubes and depots as done (hglab factory progress), the 27 sign structures stand beside their buildings in /live/world.json, and no old step of version 2 was re-laid or cleared.'
score: 0
---
The owner's instruction of 2026-11-03: the factory crew expands the factory by 200% in area and in the count of its
buildings, from a rendered plan, and carries on working. Read as twice what stood added to it: nine buildings on
67 tiles of ground became 27 on 243.

- Ground: the K column east of the campus (x 100-109, y 61-96, plots K06-K09), the flattest free ground beside the
  works in the world of tick 149812: grass to the north, forest in the middle, a sand-and-grass strip between the
  campus wall and the sea. The sixteen lots leave the office's holdings and walls, under contract like the first four.
- Works: the North Works (Gobstopper Foundry, Sherbet Spire, Licorice Loom, Toffee Kitchens, Fizz Tower), the Forest
  Works (Nougat Press, Marzipan Works, Mint Spire, Caramel Cellars, Bubblegum Mill, Butterscotch Brewery) and the
  Shore Works (Cocoa Bean Store, Whipped Cream Dairy, Jelly Bean Vats, Rock Candy Kiln, Honeycomb Hive, Candy Cane
  Lighthouse, Sugar Mouse Tower); a lane at least a tile wide round each, every door onto open ground.
- Joined: the river runs beside every new building in branches two cells wide; nineteen tubes join neighbours and
  three cross high over the campus wall; three depots hold materials beside the work. Every building, old and new,
  has its sign.
- Cost: 10,637 blocks (1,743 stone, 714 fiber, 505 wood, no ore) against about 11,800 the builders can still place
  under the world's cap of 4,096 (Toffeetrowel stands at it; GrandadPail builds nothing). The East Works are not
  walled: a ring would cost about 1,900 blocks more and run beside a resident's house at (110-112,61-64).

Evidence: `hglab factory progress`, `hglab factory check` (no problem beyond the 40 the old works already had),
and the sign structures in `/live/world.json`.
