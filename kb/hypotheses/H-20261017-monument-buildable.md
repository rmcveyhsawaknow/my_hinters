---
id: H-20261017-monument-buildable
type: hypothesis
title: A monument can be built despite the 50-item pack
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: confirmed
roles:
- physicist
- builder
- wonka
- tootles
links:
- docs/hinterglass-api.md
- agents/wonka/persona.md
- agents/tootles/persona.md
prediction: 'At least one of three mechanisms lets a single agent complete `build monument` (50 stone
  + 10 ore): (a) build consumes materials from an adjacent own or faction storehouse as well as the pack,
  (b) the 50-item capacity is per item kind rather than total, or (c) a second agent''s `give` within
  two tiles can top the builder up between a failed and a retried build in the same tick window. If none
  holds, `build monument` always returns insufficient_materials or inventory_full and the structure is
  impossible for one agent.'
falsifier: A preregistered in-world trial by one of our builders with 50 stone in a public-facing storehouse
  beside them, 10 ore in the pack, and a teammate within two tiles, in which (a), (b) and (c) each return
  insufficient_materials or inventory_full; plus a confirmation from the public event log that no monument
  has ever been built by any agent since world start.
prereg_commit: ''
window_start_utc: ''
proof_level: P1
evidence:
- public event 232, tick 4637: Cairn built a monument at (71, 70) ("THE CAIRN. First monument of Hinterglass")
- public event 209, tick 4605: Cairn built a storehouse at (73, 70), two tiles from the monument site
- public agent Cairn, created_tick 4566; 86 structures by tick 5740
- agent guide at API 0.18.0 (2026-10-17 ~22:20 UTC), `build` row: "Paid from your inventory first; whatever your pack lacks is taken from storehouses within 1 tile of you (your own tile counts) that you may take from: your own storehouses first, then the others, oldest first. Farms and caches never pay."
- agent guide at API 0.18.0, `monument` row: "60 items is more than the 50 you can carry: keep at least 10 of them in a storehouse within 1 tile of where you stand to build"
- public event 225, tick 4632: Cairn put 31 stone into the storehouse at (73, 70); events 227-230 then gather 20 stone; event 231 moves to (72, 71), adjacent to both the storehouse and the monument site; event 232 builds the monument
---

## Resolution (2026-10-17, night)

Confirmed by the game itself: at API 0.18.0 the guide documents that `build` is paid from
the pack first and the remainder from storehouses within one tile that the builder may take
from (own first, then public or faction ones, oldest first), and the monument row says to
keep at least ten of the sixty items in such a storehouse. Mechanism (a), observed in
Cairn's events earlier the same day, is the published rule. The planner now counts
reachable storehouse stock toward every build.

## Status (2026-10-17, evening)

Supported at P1, mechanism (a) favoured: a monument exists and the log shows how. Cairn,
created at tick 4566, built a storehouse at (73, 70) at tick 4605 (event 209), put 31 stone
into it at tick 4632 (event 225), gathered 20 more stone (events 227-230), stood at (72, 71),
which is adjacent to both the storehouse and the monument tile, and built the monument at
(71, 70) at tick 4637 (event 232). The pack never needed 60 items; the build drew the rest
from the adjacent own storehouse. Mechanism (b), per-item capacity, is not needed to explain
it and (c) was not used. Recipe for our builders: a storehouse within one tile of the site,
50 stone and 10 ore between pack and storehouse, then `build monument` from a tile adjacent
to both. The tower fallback stays until one of ours repeats it (that repeat is the P3).

## Why it matters

Two personas depend on a monument: Fudgewright's Everlasting Gobstopper and Lagalong' Big Thing.
The documented numbers conflict: a monument costs 60 items and a pack holds 50. Until this
is answered, every plan that depends on a monument carries a fallback (Fudgewright: the tower is
the elevator and the monument is "sold out"; Lagalong: the tower is the Big Thing).

## Cheapest test, in order

1. Read-only: scan the public event log for any `build` event with `data.type == "monument"`.
   On 2026-10-17 the world had 17 structures and none was a monument (snapshot SHA-256 in
   [the terrain fixture note](../../tests/fixtures/world/README.md)).
2. Mechanism (b): gather until the pack reads 50 of one item and try to gather a second kind;
   `inventory_full` means capacity is total.
3. Mechanism (a): stand beside a storehouse holding 50 stone with 10 ore in hand and call
   `build monument`; record the error code.
4. Mechanism (c): with 45 stone and 10 ore in hand, have a teammate `give` 5 stone and call
   `build` immediately; the pack must briefly hold 60, which `inventory_full` on `give` would
   forbid.

## Fallbacks while open

Monument plans stay optional in every persona's build priority; the tower (40 items) is the
largest guaranteed build. Both teams record which fallback they used in run records (`approach`).
