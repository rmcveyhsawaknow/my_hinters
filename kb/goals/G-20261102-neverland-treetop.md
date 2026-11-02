---
id: G-20261102-neverland-treetop
type: goal
title: 'Neverland: a treetop hideaway in its own forest'
status: active
created: '2026-11-02'
updated: '2026-11-02'
author_runtime: claude-code
roles:
- builder
- surveyor
- nibs
- tinker-bell
- lost-boy
- tootles
links:
- teams/blueprints/treetop-hideaway.yaml
- teams/neverland.yaml
- src/hglab/factory.py
- agents/nibs/persona.md
- agents/tinker-bell/persona.md
- agents/lost-boy/persona.md
- agents/tootles/persona.md
parent: null
success_test: Every step of teams/blueprints/treetop-hideaway.yaml stands in the world (hglab factory progress
  --name treetop-hideaway reads 65 of 65), its three treehouses on free forest tiles inside the ring of riddle
  signs with their decks at level 6 so no road or node under them is closed, the two rope bridges between them;
  the store under the Great Tree raised first; the wood and fiber gathered by Neverland's own crew to the
  collective's floor, never from another team's stores.
score: 0.7
---

## Rationale

The owner's instruction of 2026-11-02: the Neverland agents build a treetop hideaway in the trees of their
established area, and the agents that only explored work as a crew according to their team. The team's wanderers
had nothing to build once the ring of signs, the farms and the bridges stood, so their shifts explored. A
blueprint of their own, in the forest they already hold, gives every shift a step: Strayling fells the nearest
forest to the floor (`crew: woodcutter`), Lagalong carries what the store is shortest of (`crew: hauler`),
Stoutheart raises the store and the trees (`crew: mason`), and Tinkerglow, who keeps the gate, builds without a
crew role (`pipeline.builders`).

## Feasibility and risks

- The design passes `hglab factory check --name treetop-hideaway` against the live world of tick 142000: 65
  steps, 1468 blocks, 329 wood and 51 fiber; every box at most 160 cells, so a pack pays for any step.
- Trunks close their tiles: each stands on a forest tile with no node, structure or block, and leaves the roads
  at (72,107) and (81,103) and the opening at (84,105) open. The decks at level 6 close nothing.
- Stoutheart's `stay_inside` (Chebyshev 10 around (74,112)) covers all three trees and the works at (74,105).
- Lagalong's `patrol` holds only model plans to the coast; his crew shifts are planned by rules.
- Risk: the wood nodes inside the ring are few; the stock target of 200 wood may send the gatherers north of the
  signs, where the forest is thicker.
