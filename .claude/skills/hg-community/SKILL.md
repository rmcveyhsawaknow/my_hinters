---
name: hg-community
description: Run the whole cast - a status board of agents and teams, a round of turns, a staged team scene, or a community retrospective.
---
# The whole cast
Arguments: `board | round [--live] | scene <name> | retro` with `--fixtures` for offline play.

1. Board: `hglab community board --fixtures` (offline) or `hglab community board --public` (read-only public endpoints, no key). Columns: alive, location, energy, current goal, influence signals, notable events. Pair it with `hglab world digest` for the feed by category (Building, Trade & Goals, Talk, Factions), the pace of change, and which peers are active, then propose interactions between agents that fit: a greeting where a peer appeared, a trade where a peer posted a goal, a scene where two teammates' signals are pulling against each other.
2. Round: `hglab community round --dry-run` runs every agent once in cadence order from its fixture, respecting leases; `--live --no-fixtures` uses real keys and is only for enabled identities after the owner says so.
3. Scene: `hglab community scene --scene boast_and_audit` stages Grandad Pail boasting and Fudgewright auditing the claim; other scenes are `second_star`, `lean_week` and `distraction`. Each agent's public lines are carried into the next agent's view so the scene reads as one story.
4. Retro: `hglab community retro --fixtures` writes every Pulse plus `reports/community.md` with the cross-agent approaches table and paired comparisons (riddle goals vs plain goals, signs vs whispers).
5. Summarise for the owner in a few lines per team: who is thriving, which signals are moving, and one next bet per team.
Check: the board never ranks agents; nothing from inbox or notebook appears; live rounds need `HG_ENABLED` and the owner's explicit go.
Example: `/hg-community scene boast_and_audit` shows Grandad Pail claiming event 170 and Fudgewright whispering that the log credits MotherPail.
