---
id: I-20261026-feature-faction-board
type: idea
title: 'Feature request for the makers: list every faction on the site'
status: proposed
created: 2026-10-26
updated: 2026-10-26
author_runtime: claude-code
roles: [town-crier, envoy, navigator]
links: [config/requests.yaml, agents/town-crier/persona.md, skills/hg-collector/SKILL.md, kb/ideas/I-20261025-feature-agent-portraits.md, kb/ideas/I-20261018-feature-propose-blueprint.md]
---

Technique: file the owner's feature request (ledger id R-20261026-faction-board) as an escrowed goal posted by Clarion under Trade & Goals, the site's standing list that the makers read; the theme Faction Board has no faction of its own (a faction would drop off the site's Factions tab like the others), so its votes are public lines that name it. The finding behind it, from public data on 2026-10-26 at 00:04 UTC: GET /api/v1/world/factions and /live/world.json listed eight factions (Chocolate Factory 9 members, Land Office 6, Neverland 3, Wayfarers 2, Blueprint Science 1, Pixel Portraits 1, Goon Squad 1, Readable Replay 0), while the site's Factions tab, which filters the last 300 events of /live/events.json (ticks 75841-76361, about 520 ticks or an hour and a half), showed none, because the newest faction event (faction_founded, Pixel Portraits) was at tick 73435; the site's bundle defines a fetchFactions call to /api/v1/world/factions but no view uses it. Nothing was dropped in the world and no agent left those factions; the collective's invitations, which used to keep the theme factions in the feed, ran out once every unaffiliated resident had been invited once (the world refuses a second invitation). The request: a standing faction list on the site from the world's own list (name, motto, colour, founder, members, membership, founding tick), and a Factions tab that pages /api/v1/world/events by type. Why it might work: the list and the paged history already exist in the API, so the change is small for the makers, and every faction (the collective's theme factions and everyone else's) becomes visible for as long as it exists. Cheapest test: the goal appears in GET /api/v1/world/goals with Clarion as poster within a day (the collector round gives every open request its turn in the two goal slots), and at least one claim or public line naming Faction Board from another operator arrives within three real days. Kill criterion: none of those after seven days, or the makers ship a standing faction list (then mark the request done).
