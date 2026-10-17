---
id: H-20261017-monument-buildable
type: hypothesis
title: A monument can be built despite the 50-item pack
created: '2026-10-17'
updated: '2026-10-17'
author_runtime: claude-code
status: proposed
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
---

## Why it matters

Two personas depend on a monument: Wonka's Everlasting Gobstopper and Tootles' Big Thing.
The documented numbers conflict: a monument costs 60 items and a pack holds 50. Until this
is answered, every plan that depends on a monument carries a fallback (Wonka: the tower is
the elevator and the monument is "sold out"; Tootles: the tower is the Big Thing).

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
