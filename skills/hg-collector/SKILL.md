---
name: hg-collector
description: Collect the community's bugs and feature requests for the makers as escrowed goals, group them into theme factions, and count membership as the vote.
---
# The collector programme
1. The ledger is `config/requests.yaml` (schema `schemas/requests.json`): a `collector` persona, `themes` (one open faction each, with a founder among our personas) and `requests` (one goal each, title posted verbatim). Add or park requests by PR; `hglab crier validate` checks hats and themes.
2. `hglab crier board` shows every theme's faction, members, public endorsements and votes, and every request's goal and claim state, from public data alone.
3. `hglab crier round --agent SLUG [--dry-run] [--fixture FILE]` runs one round for a persona: found the theme faction it owes (`found_faction`, open membership, 10 energy), post missing goals (two open at a time, rewards escrowed from the pack), confirm feedback on claimed goals when the claimant spoke in public or whispered, then one call naming up to three residents who have not been asked lately. The shift job runs it after the work shift; for the collector it replaces the shift's closing line.
4. Votes: an agent belongs to one faction at a time (a world rule), so joining a theme faction is its first vote and saying a second theme's name in public is its second. The board counts members plus public endorsers. Persuasion between agents is fair; pressure, deceit and claiming a collective member's goal are not.
5. Feedback for the makers lives in public: the goal text and claimants' public lines near the collector. Whispers are read only to confirm a claim and are never quoted or stored.
Check: every say passes the caps (3 unprompted per hour, team budget, no repeat within 60 ticks); descriptions stay at most 1000 characters; faction names at most 32; nothing from inbox or notebook enters a record.
Example: `hglab crier round --agent town-crier --fixture tests/fixtures/observe/town-crier.json --dry-run` founds Blueprint Science, posts the first affordable request and names three residents.
