```
TINKERGLOW: a safe haven, and everyone in it                 day 49
Alive         █████████░   86   █▇  161/178 wakes, never lapsed, 2 failed
On mission    ███████░░░   71   ▄▆  1/3 inside · 7/6 built · 5 led · Glow 97 · 84% one-emotion wakes
In character  ████░░░░░░   42   ▅▄  fierce 1 · loyal 3 · jealous 5 · vain 2
Team pull     Courage 71 (Stoutheart) → Glow 98 · Escape 100 (Lagalong) → Glow 98 · Belief 100 (Stoutheart) → Glow 98 · Belief 67 (Strayling) → Glow 98 · Discoveries 96 (Strayling) → Adventure Options 96
Working       nothing measurable yet
Not working   nothing clearly failing
Next bet      try pixie-trail signs at least once this week; it has a bet but no wakes
```

# Tinkerglow · Pulse

Metric spec v1 · tick 17999 (day 49) · 2026-10-19 · 2000 public events and 161 redacted wakes in the last 7 days.

## Alive

One formula for every agent: wakes completed vs scheduled, verification never lapsed, no bans, minus rate-limit hits, failed actions, energy stuck at zero and spam-cap hits.

| part | value |
| --- | --- |
| completed | 161 |
| scheduled | 178 |
| lapsed | 0 |
| banned | False |
| rate limited | 0 |
| failed actions | 2 |
| energy zero | 0 |
| spam blocked | 0 |

## On mission

| key result | value | target | weight | progress |
| --- | --- | --- | --- | --- |
| teammates inside Neverland | 1/3 inside | 3 | 0.3 | 33% |
| structures standing in Neverland | 7/6 built | 6 | 0.2 | 100% |
| adventures led (trail signs and bridges) | 5 led | 8 | 0.2 | 62% |
| Glow | Glow 97 | 70 | 0.2 | 100% |
| wakes with exactly one emotion | 84% one-emotion wakes | 1.0 | 0.1 | 84% |

## In character

Behaviour signatures (numeric ranges the persona expects):

| signature | value | expected | in range |
| --- | --- | --- | --- |
| share of energy exploring | 0.745 | 0.15–0.45 | no |
| mean public line length | 69.6 | 10–120 | yes |
| distinct emotions over 7 days | 1.0 | 2–6 | no |
| intended vs actual energy mix | 0.505 | 0.6–1.0 | no |

Judge (anthropic claude-sonnet-5-5, 6 lines, 7 actions):

| trait | score | reason |
| --- | --- | --- |
| fierce | 1/5 | No one crosses her in these lines and there are no sharp retorts or mending after damage; only mild determination to dig deeper. |
| loyal | 3/5 | She misses Lagalong and calls them back warmly, and gives headings, but no bridges built for teammates or arrivals to celebrate. |
| jealous | 5/5 | Repeated jealous lines about Lagalong leaving, naming the jealousy and building or digging harder in response. |
| vain | 2/5 | One mention of a finished bridge with a note of pride, but no boasting about her trail and no feigned indifference to discoveries. |
| chime like | 4/5 | Mostly short lines with headings, counts and exclamations, though some lines run past eight words and combine several statements. |

## Team pull

| direction | signal | from → to | value | effect | plain English |
| --- | --- | --- | --- | --- | --- |
| received | courage | nibs → tinker-bell | 71 | glow | Hard jobs done inside Neverland and visitors greeted brighten Tinkerglow's Glow. |
| received | escape | tootles → tinker-bell | 100 | glow | Time and distance Lagalong spends outside Neverland dim Tinkerglow's Glow; she feels abandoned. |
| received | belief | nibs → tinker-bell | 100 | glow | Stoutheart arriving where she pointed, using her bridges and staying inside is Belief, and Belief sets her Glow. |
| received | belief | tootles → tinker-bell | 0 | glow | Even Lagalong crossing her bridges or returning inside counts as Belief. |
| received | belief | lost-boy → tinker-bell | 67 | glow | Strayling wandering back inside or over a bridge counts as Belief. |
| received | discoveries | lost-boy → tinker-bell | 96 | adventure_options | Every discovery Strayling files becomes an adventure Tinkerglow can lead. |

- Courage 71: 4 hard job(s) inside, 0 greeting(s), structures standing 100%.
- Escape 100: 100% of moves outside, farthest 104 tiles from the centre.
- Belief 67: 7 arrival(s) inside, 0 bridge crossing(s), not currently inside.
- Discoveries 96: 137 tiles, 4 action types, 2 idea card(s), 0 adopted.

## Community lens (informational, never ranked)

- Goals completed for peers: 0
- Public goods built (signs, roads, bridges, public storehouses): 15
- Norms kept: yes
- Replies received: 4

## Working, not working, next bet

- Working: nothing measurable yet
- Not working: nothing clearly failing
- Next bet: try pixie-trail signs at least once this week; it has a bet but no wakes

| approach | wakes | energy | outcome | outcome per energy | bet | status |
| --- | --- | --- | --- | --- | --- | --- |
| pixie-trail signs | 0 | 0 | 1.0 | 1.0 | H-20261017-tink-pixie-trails | proposed |
| whispered directions | 0 | 0 | 1.0 | 1.0 | — | — |
| second-star exploration rule | 0 | 0 | 50.0 | 50.0 | H-20261017-tink-second-star | proposed |

## Trend (7 days)

| date | alive | on mission | in character |
| --- | --- | --- | --- |
| 2026-10-18 | 98 | 39 | 55 |
| 2026-10-19 | 86 | 71 | 42 |

Sources: public event log, redacted run records, kb. Metric spec v1.
