---
id: G-20261102-the-larger-new-york-replica-every-building-with-a-sign
type: goal
title: The larger New York replica, every building with a sign
status: active
created: '2026-11-02'
updated: '2026-11-02'
author_runtime: human
roles: [builder, broker, surveyor]
links:
  - teams/blueprints/midtown.yaml
  - teams/blueprints/central-park.yaml
  - teams/blueprints/lower-manhattan.yaml
  - config/plots.yaml
  - teams/atelier.yaml
  - src/hglab/factory.py
parent: null
success_test: 'Every section of the three New York designs has a sign step beside it that stands in the world (reconcile marks it done); Midtown and Central Park rise only on lots the office has deeded to Plumbline; the factory crew records placements on them only after every factory step is done.'
score: 0
---
The owner's brief of 2026-11-02 (evening): when the crew is finished with the factory, resume with a larger New
York replica - Central Park and Midtown - and each building or monument should have a sign next to it.

- Signs: a section's `sign: {x, y, text}` is its last step, a `build sign` on the tile beside it (one wood). The
  words are the Atelier's own, a fact or two each, never copied. Lower Manhattan's twenty-one buildings got theirs
  the same evening.
- Ground: Midtown's nine lots north of Lower Manhattan and Central Park's nine round the inland lake, grass the
  office had staked, no stone or ore node, no resident's holding; four site requests for Plumbline offered one
  after another (`after`), all eighteen lots off the office's holdings.
- Order: the Atelier builds Lower Manhattan, then Midtown, then Central Park; the factory crew follows once the
  factory stands (`next_blueprint` lists).

Evidence: the ledgers under `runs/local/blueprints/` (`hglab factory progress --name midtown|central-park`), the
office's deed ticks in `config/plots.yaml`, and the sign structures in `/live/world.json`.
