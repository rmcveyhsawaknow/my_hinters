---
name: hg-new-agent
description: Create a new persona through a short guided interview, then generate persona, metrics, team updates, kb goals, approach bets and a disabled workflow.
---
# New agent, guided
Interview the owner in one or two short batches with sensible defaults, then generate everything with `hglab persona new --answers FILE`.

1. Batch one (concept): inspiration and concept in our own words; the in-world name, checked with `hglab persona check-name NAME` (3-24 chars, `[A-Za-z0-9_-]`, read-only lookup); team (new or existing) and relationships; one-sentence intent and what success looks like.
2. Batch two (mechanics): 5-7 traits each with how it shows up in-world; voice rules; knobs (cadence cron and jitter, rest probability, actions per wake 1-4, energy reserve at or above 20, risk, exploration, territory mode, social rate within the team budget, intended mix summing to 1); roles (hats); mood model and quirk; influence links `{from, signal, to, effect, plain_english}`; 3-5 key results and 2+ behaviour signatures; 2-3 approach bets with prediction and falsifier; boundaries.
3. Write the answers to a YAML file (see `docs/personas-and-measurement.md` for the keys), then run `hglab persona new --answers answers.yaml`. It creates `agents/<slug>/persona.md` and `metrics.yaml`, adds the member and links to `teams/<team>.yaml`, appends a disabled identity to `config/agents.yaml`, files a kb goal and the approach bets, and writes `.github/workflows/agent-<slug>.yml`.
4. Deepen the bible by hand: backstory, voice, signature moves, ironies, boundaries, a few fresh example lines. Keep the two inherited rules: character vs conduct (vices in voice and toward our own team's resources only; honest to peers) and originality (no lyrics, no reproduced dialogue).
5. Validate and preview: `hglab persona validate`, `hglab sync`, write a fixture (`tests/fixtures/make_fixtures.py` is the model), then `hglab tick --agent <slug> --dry-run --fixture ...` and `hglab pulse --agent <slug> --fixtures`.
6. Offer registration without performing it: `hglab register --name <Name>` is a live, permanent, owner-approved step (at most 5 registrations per hour from one IP).
Check: profile bio says the agent is a character in an ongoing story by the collective; no peer is named or mocked anywhere in the bible; the team's say budget still covers every member.
Example: an answers file with `slug: captain-hook`, `team: pirates`, three traits and one bet produces a valid persona, a new team file and a caller workflow in one command.
