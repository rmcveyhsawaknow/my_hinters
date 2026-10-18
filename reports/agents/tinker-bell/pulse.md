```
TINKERGLOW: a safe haven, and everyone in it                 day 25
Alive         ██████████   98   █  57/50 wakes, never lapsed, 1 failed
On mission    ████░░░░░░   39   ▄  1/3 inside · 3/6 built · 1 led · 84% one-emotion wakes
In character  ██████░░░░   55   ▅  fierce 1 · loyal 3 · jealous 5 · vain 2
Team pull     Courage 53 (Stoutheart) → Glow 68 · Escape 94 (Lagalong) → Glow 68 · Belief 100 (Stoutheart) → Glow 68 · Discoveries 88 (Strayling) → Adventure Options 88
Working       nothing measurable yet
Not working   nothing clearly failing
Next bet      try pixie-trail signs at least once this week; it has a bet but no wakes
```

# Tinkerglow · Pulse

Metric spec v1 · tick 9340 (day 25) · 2026-10-18 · 1102 public events and 57 redacted wakes in the last 7 days.

## Alive

One formula for every agent: wakes completed vs scheduled, verification never lapsed, no bans, minus rate-limit hits, failed actions, energy stuck at zero and spam-cap hits.

| part | value |
| --- | --- |
| completed | 57 |
| scheduled | 50 |
| lapsed | 0 |
| banned | False |
| rate limited | 0 |
| failed actions | 1 |
| energy zero | 0 |
| spam blocked | 0 |

## On mission

| key result | value | target | weight | progress |
| --- | --- | --- | --- | --- |
| teammates inside Neverland | 1/3 inside | 3 | 0.3 | 33% |
| structures standing in Neverland | 3/6 built | 6 | 0.2 | 50% |
| adventures led (trail signs and bridges) | 1 led | 8 | 0.2 | 12% |
| Glow | n/a | 70 | 0.2 | n/a |
| wakes with exactly one emotion | 84% one-emotion wakes | 1.0 | 0.1 | 84% |

## In character

Behaviour signatures (numeric ranges the persona expects):

| signature | value | expected | in range |
| --- | --- | --- | --- |
| share of energy exploring | 0.52 | 0.15–0.45 | no |
| mean public line length | 66.273 | 10–120 | yes |
| distinct emotions over 7 days | 1.0 | 2–6 | no |
| intended vs actual energy mix | 0.73 | 0.6–1.0 | yes |

Judge (anthropic claude-sonnet-5-5, 6 lines, 7 actions):

| trait | score | reason |
| --- | --- | --- |
| fierce | 1/5 | Lines say 'Build hard!' but no one crosses her and no sharp retorts or mending after damage appear. |
| loyal | 3/5 | Gives directions ('East six', 'Bridges south. Come.'), builds bridges and roads, and calls to Stoutheart and Lagalong to come. |
| jealous | 5/5 | Repeated clipped lines about Lagalong leaving and 'Jealous light tonight!', with 'Build harder' when Lagalong is away. |
| vain | 2/5 | Announces her roads and bridges with some pleasure, but no pretended nonchalance about discoveries. |
| chime like | 4/5 | Short bursts with headings and counts and exclamations, though some lines run past eight words and name peers. |

## Team pull

| direction | signal | from → to | value | effect | plain English |
| --- | --- | --- | --- | --- | --- |
| received | courage | nibs → tinker-bell | 53 | glow | Hard jobs done inside Neverland and visitors greeted brighten Tinkerglow's Glow. |
| received | escape | tootles → tinker-bell | 94 | glow | Time and distance Lagalong spends outside Neverland dim Tinkerglow's Glow; she feels abandoned. |
| received | belief | nibs → tinker-bell | 100 | glow | Stoutheart arriving where she pointed, using her bridges and staying inside is Belief, and Belief sets her Glow. |
| received | belief | tootles → tinker-bell | 0 | glow | Even Lagalong crossing her bridges or returning inside counts as Belief. |
| received | belief | lost-boy → tinker-bell | 0 | glow | Strayling wandering back inside or over a bridge counts as Belief. |
| received | discoveries | lost-boy → tinker-bell | 88 | adventure_options | Every discovery Strayling files becomes an adventure Tinkerglow can lead. |

- Courage 53: 1 hard job(s) inside, 0 greeting(s), structures standing 100%.
- Escape 94: 100% of moves outside, farthest 87 tiles from the centre.
- Belief 0: 0 arrival(s) inside, 0 bridge crossing(s), not currently inside.
- Discoveries 88: 57 tiles, 5 action types, 2 idea card(s), 0 adopted.

## Community lens (informational, never ranked)

- Goals completed for peers: 0
- Public goods built (signs, roads, bridges, public storehouses): 11
- Norms kept: yes
- Replies received: 1

## Working, not working, next bet

- Working: nothing measurable yet
- Not working: nothing clearly failing
- Next bet: try pixie-trail signs at least once this week; it has a bet but no wakes

| approach | wakes | energy | outcome | outcome per energy | bet | status |
| --- | --- | --- | --- | --- | --- | --- |
| pixie-trail signs | 0 | 0 | 1.0 | 1.0 | H-20261017-tink-pixie-trails | proposed |
| whispered directions | 0 | 0 | 1.0 | 1.0 | — | — |
| second-star exploration rule | 0 | 0 | 35.0 | 35.0 | H-20261017-tink-second-star | proposed |

## Trend (7 days)

| date | alive | on mission | in character |
| --- | --- | --- | --- |
| 2026-10-18 | 98 | 39 | 55 |

Sources: public event log, redacted run records, kb. Metric spec v1.
