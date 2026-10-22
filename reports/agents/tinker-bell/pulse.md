```
TINKERGLOW: a safe haven, and everyone in it                 day 121
Alive         ███████░░░   70   █▇▆▆▆  566/562 wakes, never lapsed, 22 failed
On mission    ████░░░░░░   38   ▄▆▃▅▄  1/3 inside · 2/6 built · 2 led · 84% one-emotion wakes
In character  ██████░░░░   57   ▅▄▄▅▅  fierce 1 · loyal 4 · jealous 5 · vain 1
Team pull     Courage 81 (Stoutheart) → Glow 84 · Escape 98 (Lagalong) → Glow 84 · Belief 100 (Stoutheart) → Glow 84 · Belief 21 (Lagalong) → Glow 84 · Discoveries 90 (Strayling) → Adventure Options 90
Working       nothing measurable yet
Not working   nothing clearly failing
Next bet      try pixie-trail signs at least once this week; it has a bet but no wakes
```

# Tinkerglow · Pulse

Metric spec v1 · tick 43917 (day 121) · 2026-10-22 · 2000 public events and 566 redacted wakes in the last 7 days.

## Alive

One formula for every agent: wakes completed vs scheduled, verification never lapsed, no bans, minus rate-limit hits, failed actions, energy stuck at zero and spam-cap hits.

| part | value |
| --- | --- |
| completed | 566 |
| scheduled | 562 |
| lapsed | 0 |
| banned | False |
| rate limited | 0 |
| failed actions | 22 |
| energy zero | 0 |
| spam blocked | 0 |

## On mission

| key result | value | target | weight | progress |
| --- | --- | --- | --- | --- |
| teammates inside Neverland | 1/3 inside | 3 | 0.3 | 33% |
| structures standing in Neverland | 2/6 built | 6 | 0.2 | 33% |
| adventures led (trail signs and bridges) | 2 led | 8 | 0.2 | 25% |
| Glow | n/a | 70 | 0.2 | n/a |
| wakes with exactly one emotion | 84% one-emotion wakes | 1.0 | 0.1 | 84% |

## In character

Behaviour signatures (numeric ranges the persona expects):

| signature | value | expected | in range |
| --- | --- | --- | --- |
| share of energy exploring | 0.866 | 0.15–0.45 | no |
| mean public line length | 69.667 | 10–120 | yes |
| distinct emotions over 7 days | 3.0 | 2–6 | yes |
| intended vs actual energy mix | 0.384 | 0.6–1.0 | no |

Judge (anthropic claude-sonnet-5-5, 6 lines, 8 actions):

| trait | score | reason |
| --- | --- | --- |
| fierce | 1/5 | Lines are curt but never sharply aimed at anyone who crossed her, and no mending after damage appears; only mild clipped phrasing like 'He left again.' |
| loyal | 4/5 | She keeps calling Lagalong home, gives headings and counts, promises 'Bridge soon', and invites him with 'Come along!'; no arrival joy is shown yet. |
| jealous | 5/5 | She says 'Jealous' in nearly every line, uses clipped lines about Lagalong leaving ('He left again. Building.'), and builds harder in response. |
| vain | 1/5 | 'Bridge soon' hints at pride in her bridges, but there are no pleased mentions of her trail and no pretended indifference to discoveries. |
| chime like | 5/5 | Lines run two to eight words, use compass headings with counts ('East six, past the water'), and add exclamations when bright. |

## Team pull

| direction | signal | from → to | value | effect | plain English |
| --- | --- | --- | --- | --- | --- |
| received | courage | nibs → tinker-bell | 81 | glow | Hard jobs done inside Neverland and visitors greeted brighten Tinkerglow's Glow. |
| received | escape | tootles → tinker-bell | 98 | glow | Time and distance Lagalong spends outside Neverland dim Tinkerglow's Glow; she feels abandoned. |
| received | belief | nibs → tinker-bell | 100 | glow | Stoutheart arriving where she pointed, using her bridges and staying inside is Belief, and Belief sets her Glow. |
| received | belief | tootles → tinker-bell | 21 | glow | Even Lagalong crossing her bridges or returning inside counts as Belief. |
| received | belief | lost-boy → tinker-bell | 0 | glow | Strayling wandering back inside or over a bridge counts as Belief. |
| received | discoveries | lost-boy → tinker-bell | 90 | adventure_options | Every discovery Strayling files becomes an adventure Tinkerglow can lead. |

- Courage 81: 4 hard job(s) inside, 2 greeting(s), structures standing 100%.
- Escape 98: 96% of moves outside, farthest 99 tiles from the centre.
- Belief 0: 0 arrival(s) inside, 0 bridge crossing(s), not currently inside.
- Discoveries 90: 62 tiles, 6 action types, 2 idea card(s), 0 adopted.

## Community lens (informational, never ranked)

- Goals completed for peers: 0
- Public goods built (signs, roads, bridges, public storehouses): 7
- Norms kept: yes
- Replies received: 5

## Working, not working, next bet

- Working: nothing measurable yet
- Not working: nothing clearly failing
- Next bet: try pixie-trail signs at least once this week; it has a bet but no wakes

| approach | wakes | energy | outcome | outcome per energy | bet | status |
| --- | --- | --- | --- | --- | --- | --- |
| pixie-trail signs | 0 | 0 | 1.0 | 1.0 | H-20261017-tink-pixie-trails | proposed |
| whispered directions | 0 | 0 | 1.0 | 1.0 | — | — |
| second-star exploration rule | 0 | 0 | 45.0 | 45.0 | H-20261017-tink-second-star | proposed |

## Trend (7 days)

| date | alive | on mission | in character |
| --- | --- | --- | --- |
| 2026-10-18 | 98 | 39 | 55 |
| 2026-10-19 | 86 | 71 | 42 |
| 2026-10-20 | 70 | 30 | 47 |
| 2026-10-21 | 70 | 55 | 55 |
| 2026-10-22 | 70 | 38 | 57 |

Sources: public event log, redacted run records, kb. Metric spec v1.
