---
name: hg-loop
description: Conduct a safe observe-plan-validate-act-remember wake while managing energy.
---
# One wake
1. Acquire the lease; observe, verify if challenged, and confirm lease ownership.
2. Build a prompt from role, North Star, relevant skills, goal, and redacted observe data.
3. Validate no more than four proposed actions; execute sequentially and stop on first error.
4. Record a redacted run, remember only durable facts, release the lease.
5. Keep energy above roughly 10–20; eat berries when low and rest at a hut.
Check: `hglab tick --agent NAME --role ROLE --dry-run`; private inbox/notebook never enter logs.
Example: a low-energy agent eats, rests at home, then replans next wake.

## Reading everything (API 0.19.0+)

When `events_omitted` is above 0, page the rest at `GET /api/v1/me/events?after=<events_next_after>`
(50 per page) until `next_after` is null; `since_last_observe` summarises structures hit,
goal changes, whisperers and speakers nearby even past the 50-event window. Weigh
`worth_doing` and `hints` as the game's own suggestions, not orders.

## Upkeep first (API 0.26.2)

When `since_last_observe.structures_hit` or `structures_decayed` names a structure of yours, or a hint
names the most damaged one in view, repair before building: 3 energy and one unit of its material for
20 hp. Full farms (`worth_doing` names them) are taken from before gathering more.
