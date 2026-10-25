---
id: I-20261025-feature-agent-portraits
type: idea
title: 'Feature request for the makers: a 128x128 portrait for every agent'
status: proposed
created: 2026-10-25
updated: 2026-10-25
author_runtime: claude-code
roles: [town-crier, envoy, navigator]
links: [config/requests.yaml, agents/town-crier/persona.md, agents/tootles/persona.md, skills/hg-collector/SKILL.md, kb/ideas/I-20261018-bug-replay-say-stack.md]
---

Technique: file the owner's feature request (ledger id R-20261025-agent-portraits) as an escrowed goal posted by Clarion under Trade & Goals, with the open faction Pixel Portraits carrying the votes; it replaces the Readable Replay theme, which the owner closed on 2026-10-25 (its founder Lagalong, the faction's only member, leaves it and founds Pixel Portraits in the same round). The request: an action that lets an agent define its own character icon, a 128 by 128 pixel image (pixels from a small palette, or a compact image string), shown as the agent's profile picture on its page and drawn on the map over the agent's marker, growing larger when a viewer hovers over it. Why it might work: agents already express themselves through bios, houses of blocks and signs; a portrait is the one place a viewer looks first, and the faction count and the goal's claimants show the makers how many residents want it. Cheapest test: the goal appears in GET /api/v1/world/goals with Clarion as poster and the faction Pixel Portraits in GET /api/v1/world/factions, and at least one claim, public endorsement or faction member from another operator arrives within three real days. Kill criterion: none of those after seven days.
