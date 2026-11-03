---
id: G-20261103-nobody-who-can-build-stands-idle
type: goal
title: Nobody who can build stands idle while another team's blueprint is open
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, conductor]
links:
  - src/hglab/help.py
  - src/hglab/planner.py
  - src/hglab/local/routing.py
  - src/hglab/wake.py
  - teams/neverland.yaml
  - tests/test_help.py
parent: G-20261102-every-hand-builds-and-no-store-blocks-it
success_test: 'Within two days of the merge the run records show wakes with approach help by members of at least two teams (hglab local memory, or grep "a hand lent to" runs/), each settled into another team''s blueprint ledger, and Neverland''s hands show wakes with approach roam between the hideaway''s trees.'
score: 0
---
The owner's instruction of 2026-11-03 (evening): consider the local memory graph and coordinate every team's effort
so the world is built as fast as possible; a shift in which an agent is not building is a shift spent helping
another team with what it is building.

- hglab.help: a crew hand whose pipeline has nothing for it this wake, or a builder (Tinkerglow, Plumbline, the
  registrar) whose own designs are done or waiting on a deed, takes a step of the nearest other team's open
  blueprint (factory.plan_step with hands=True: any section, nearest and payable first), its own pack and its
  faction's stores paying, settled into that team's ledger like any other step. The world's cap of 4,096 blocks is
  per owner, so more hands on one design is also more room under it.
- The memory graph routes idle hands there (hglab.local.routing: approach `help` when the hand's own designs are
  done or its team has none), the supervisor's cast carries every team's pipeline to the planner, and the planner
  falls back to helping whenever the team's own pipeline yields nothing (the fill-board cap included).
- Who keeps their own ways: GrandadPail (builds nothing, the owner, 2026-10-24), the fool and the crier (they speak),
  the Navy (it charts, on a model plan within its own budget).
- Neverland's hands walk the hideaway's grounds, one move a wake tree to tree, when nothing is left to raise or
  help with (`pipeline.roam`, hglab.help.plan_roam): walkers in this world have no height, so the decks are lived
  under, and the rope ladders make them read as reachable.

Evidence: run records with `approach: help` and reasons beginning "a hand lent to", the other team's ledger
naming the helper, and `approach: roam` records for Neverland.
