---
id: G-20261103-the-office-builds-the-larger-new-york
type: goal
title: The land office stops its walls and builds the larger New York
status: active
created: '2026-11-03'
updated: '2026-11-03'
author_runtime: human
roles: [builder, broker]
links:
  - teams/exchange.yaml
  - teams/blueprints/midtown.yaml
  - teams/blueprints/central-park.yaml
  - teams/blueprints/uptown.yaml
  - src/hglab/crew.py
  - src/hglab/factory.py
  - tests/test_office_builds.py
parent: G-20261102-the-larger-new-york-replica-every-building-with-a-sign
success_test: 'The midtown, central-park and uptown ledgers (hglab factory progress) record steps placed by the six office members (LandBroker, Boundstone, Fellwright, Sheafwell, Drayhand, Lintelstave) within a day of the merge, no office member raises a wall after it, and the office stores still take every give (no give refused for a full store in the public events).'
score: 0
---
The owner's instruction of 2026-11-03 (evening): the land office stops building walls for now, and the team that
walled so well turns the same discipline to the larger New York plan: Midtown, Central Park and Uptown, north of
Lower Manhattan, in that order, and Nintendo Land after them.

- `claims.walls.enabled: false`: the mechanism stands (hglab.walls, its tests) for when the owner turns it back on;
  no hand draws stone for a wall or walls a lot while it is off.
- `pipeline.blueprint: midtown`, `next_blueprint: [central-park, uptown, nintendo-land]`, `focus: blueprint`: every
  hand takes the next step it can pay for or fetch before unloading or gathering (hglab.crew a1c); a heavy pack lays
  what its main load pays for first; the registrar builds in his work shifts (no crew knob; the blueprint step).
- The office raises a client's design on its own staked lots before the deed is paid (hglab.factory.lands_own):
  the lots are the office's until Plumbline buys them, and the deed carries the ground with what stands on it. The
  Atelier's own builder still waits for the deed (land_wanted), as before.
- The tills, the overflow store beside a full one and the fill-board throttle come before the blueprint in the
  mason's order, so a full store still blocks no give.

Evidence: `hglab factory progress --name midtown` naming office members; the supervisor log's shift summaries
("the Midtown blueprint: ...") for office-* jobs; no "wall" in the office's run records after the merge.
