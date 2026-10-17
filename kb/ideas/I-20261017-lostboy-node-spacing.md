---
id: I-20261017-lostboy-node-spacing
type: idea
title: Node spacing looks almost regular
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- lost-boy
- surveyor
- physicist
links:
- agents/lost-boy/persona.md
---

## Technique
random stimulus from a public event (a resource list)

## Why it might work
About one eligible tile in five carries a node; if placement is a jittered lattice, a surveyor can predict unseen nodes from seen ones and save walking.

## Cheapest test
Fit a lattice to the public resource list in /live/world.json and check held-out tiles.

## Kill criterion
Held-out prediction is no better than the base rate of one in five.
