---
id: C-20261017-single-landmass
type: claim
title: The public terrain is one connected landmass; no island is reachable only by bridge
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
roles:
- observer
- physicist
- tinker-bell
links:
- tests/fixtures/world/README.md
- teams/neverland.yaml
proof_level: P2
evidence:
- snapshot https://hinterglass.com/live/world.json fetched 2026-10-17T14:11:24Z, tick 3702, SHA-256 21767406ecfebaf9df2e7c1085f634a4a7a343632f076908f44478f94e2cb561
- extracted rows tests/fixtures/world/terrain.txt, SHA-256 9b844dbc4018c874905df3911268847a89e500e23507feab16ab7fa671f9d529
prove_cmd: python analysis/landmass.py tests/fixtures/world/terrain.txt
expected: 1
tolerance: 0
---

## Claim

Treating `s`, `g`, `f` and `h` as walkable and allowing diagonal steps (Chebyshev moves), a
flood fill over the 128x128 terrain finds exactly one walkable component of 7755 tiles.
There is therefore no land that can be reached only by bridging shallow water, which is the
spot Neverland wanted. The fallback recorded in `teams/neverland.yaml` is the farthest grass
from existing homesteads with shallow water beside it.

Counts in the same snapshot: deep water 7239, grass 4043, forest 1785, sand 1280, shallow
water 1221, hills 647, mountain 169.

## Falsification attempts

- Re-run with 4-neighbour connectivity: the component count may rise if diagonal-only
  necks exist; the world moves diagonally, so 8-neighbour is the relevant rule.
- Terrain can change only through structures (bridges, walls); a wall-ringed area is not an
  island in this sense because walls are legal to demolish.

P2: `analysis/landmass.py` regenerates the count from the archived rows and `hglab prove` checks it in CI. P3 needs an independent re-run on another runtime.
