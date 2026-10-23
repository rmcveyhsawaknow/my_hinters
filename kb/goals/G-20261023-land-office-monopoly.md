---
id: G-20261023-land-office-monopoly
type: goal
title: 'The land office owns its best lots, works them and sells the yield'
status: proposed
created: '2026-10-23'
updated: '2026-10-23'
author_runtime: claude-code
roles:
- broker
- surveyor
- builder
- land-broker
- office-quarrier
- office-feller
- office-reaper
- office-drayman
- office-steward
links:
- teams/exchange.yaml
- config/plots.yaml
- src/hglab/lots.py
- src/hglab/land.py
- src/hglab/crew.py
- agents/land-broker/persona.md
parent: null
success_test: Within 14 real days the public log shows the office's holdings firmed (claim signs rewritten), the five hands giving stone, ore, wood, fiber and berries into office storehouses, depots standing on the three best holdings, at least ten goods sales listed from the vault and at least five settled by other residents.
score: 0.7
---

The owner's instruction of 2026-10-23: LandBroker has staked most of the island; now it makes firm claims on the most valuable lots, works their resources into a central store through five hands that report to it, and sells from that store, toward a monopoly on the island's resources. The claims block in the Exchange's pipeline names the holdings; the ledger's sales list the goods. Two limits stand by design: the collective's floor of five near the spawn and other residents' homesteads (the guide asks that the spawn area is never stripped), and the rule that a claim is a public record, never a wall across anyone's path.
