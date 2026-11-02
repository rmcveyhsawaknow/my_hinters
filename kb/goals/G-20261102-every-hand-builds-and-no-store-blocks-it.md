---
id: G-20261102-every-hand-builds-and-no-store-blocks-it
type: goal
title: Every hand builds and no store blocks it
status: active
created: '2026-11-02'
updated: '2026-11-02'
author_runtime: human
roles: [builder, broker]
links:
  - src/hglab/quartermaster.py
  - src/hglab/crew.py
  - agents/loompa-hauler/persona.md
  - teams/chocolate-factory.yaml
parent: null
success_test: 'Over three days of run records no give by a collective hand is refused as inventory_full, every readable store of the works stands at or under 375 items at each wake that reads it, and every crew hand records at least one accepted place or build per shift while the team has an undone blueprint step.'
score: 0
---
The owner's brief of 2026-11-02, after the agents came back to the host: the explore-only agents become crew
that builds by team; the Chocolate Factory keeps building onto the factory (tubes and structures joining
every building); Neverland raises a treetop hideaway in its own forest; the land office hands build out the
walls round the staked lots; and one existing agent sees that building is never blocked by a full store -
when a store fills, another rises beside it and the loads are balanced, every store kept to three quarters.

What this item records:

- Caramelcart, the factory's hauler, is the quartermaster (`knobs.quartermaster`, `hglab.quartermaster`):
  the mark is 375 of 500; past it, the excess moves into the store beside, or another store rises beside the
  full one and the full one pays. Only stores whose contents show can be judged: the office's stores are
  opaque to the factory, so the office's own mason keeps raising another beside a full one.
- A crew hand whose works holds every kind of the stock at target takes a blueprint step before another
  load (`crew.stock_at_target`), so the hands build whenever there is something to build.

Evidence: run records under `runs/<date>/` (the `approach` and `results` of the hands' wakes), and the
blueprint ledgers under `runs/local/blueprints/`.
