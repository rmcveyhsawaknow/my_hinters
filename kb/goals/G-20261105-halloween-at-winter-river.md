---
id: G-20261105-halloween-at-winter-river
type: goal
title: Halloween at Winter River, after every work stands and is signed
status: active
created: '2026-11-05'
updated: '2026-11-05'
author_runtime: human
roles: [builder, surveyor]
links:
  - teams/blueprints/halloween.yaml
  - teams/blueprints/signposts.yaml
  - tests/test_halloween.py
  - src/hglab/factory.py
  - teams/chocolate-factory.yaml
  - teams/atelier.yaml
  - teams/exchange.yaml
  - teams/neverland.yaml
parent: null
success_test: 'The signposts ledger records all 16 signs done once nintendo-land is complete, and the halloween ledger records all 663 of its steps done (hglab factory progress --name signposts, --name halloween); hglab factory check --name halloween reports no problem against the public world, and the 21 Halloween signs and 16 signposts stand in /live/world.json (or are recorded blocked by another structure on their tile).'
score: 0
---
The owner's brief of 2026-11-05: when Nintendo Land is complete, label every structure in every area with a sign as
the New York replica is labelled; when all the building is complete and the signs made, a Halloween area with all
the creepy things, the striped ghost of the film Beetlejuice as its main character, laid out after the film's model
town of Winter River and its opening, which glides over the woods and the town to the house on the hill before a
spider on that house's roof shows the whole town is a model in the attic. Inspired by the film, built in our own
words and shapes: names of places and things only, no quoted lines.

- The signposts (`teams/blueprints/signposts.yaml`, `after: [nintendo-land]`): every design's buildings already carry
  their signs as their last steps, and every pier and the causeway carries the Admiralty's. What none labels gets a
  sign here, 16 in all (style `landmark`, the sign alone): the hideaway's three oldest trees, eleven members' homes and
  towers, the factory's west gate and the vault of the golden tickets. Tinkerglow's hut by the spawn (66,54) and
  Fudgewright's tower inside the campus (87,91) have no free tile beside them and stay unlabelled. The Navy's rules
  write a blank shore sign of its own again (Pier-10's stood empty).
- Halloween at Winter River (`teams/blueprints/halloween.yaml`, `after` naming every other design): x 95-114, y 28-54,
  21 lots between Nintendo Land and the office's walled lots, held by contract (no deed). The woods and the
  Maitland house on its green hill (a spider as big as the roof on it) on the west bank of a blue slab river, the red
  covered bridge, Village Street with the white church, Maitland Hardware, the library and its lions, Miss Shannon's
  School for Girls, the fire house and the barber shop, the town green, the model graveyard with the crypt with the
  striped door and the striped ghost (the tallest piece, at the ceiling), the Handbook for the Recently Deceased, the
  Waiting Room, the sandworm of Titan rearing out of the dunes, the haunted woods, a pumpkin patch with a scarecrow,
  the great jack-o'-lantern, a house with dark windows and the lantern house. 21 sections, 663 steps, 6,986 blocks:
  1,379 stone, 317 wood and 255 fiber items, no ore; every box at most 160 cells; a sign beside every section.
- New in the expander: style `sculpture` (boxes of cells from the section's corner, for what no style draws), style
  `landmark` (a sign beside what already stands), a section's own `foundation_block` (the green hill) and a design's
  `after` (it opens only when the designs it names are done). A sign or depot whose tile another structure took is
  recorded blocked, so a design still completes.
- Who builds it: the end of every team's `next_blueprint`: nintendo-land, signposts, halloween.

Evidence: `hglab factory check --name halloween` and `--name signposts` (no problems against the world of tick
170600), `hglab factory show --name halloween`, tests/test_halloween.py, and later the ledgers and the sign structures
in `/live/world.json`.
