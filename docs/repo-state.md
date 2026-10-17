# Repository state (2026-10-17)

Written at the start of the personas, teams and Pulse session. Where the code and
[the jumpstart spec](jumpstart-prompt.md) differ, the code is the truth; this page
records the differences so they stay visible.

## What exists and works

- `hglab` CLI (Typer) with `doctor`, `observe`, `tick`, `act`, `verify`, `register`,
  `lease`, `kb`, `config validate`, `sync`, `observatory collect`, `prove`, `digest`,
  `guide`, `key store`. Entry point is `hglab`; Python 3.12.
- Safety core: typed client with token bucket and retries, action validator with role
  allowlists, text limits, URL and secret filters, spam caps (3 says/hour, 2 open goals,
  no repeated text within 60 ticks, 4 actions per wake), redaction of inbox and notebook,
  notebook lease with read-after-write race detection, redacted run records in `runs/`.
- 17 role charters, 21 skills, kb with templates and seeds, JSON Schemas for kb items,
  roles, skills and configs. `hglab sync` generates `.claude/agents` and `.claude/skills`.
- Workflows: `ci.yml`, `agent-heartbeat.yml` (matrix over `config/agents.yaml`),
  `observatory.yml`, `science-digest.yml`. All agent jobs are gated by `HG_ENABLED`.
- Checks at session start: 29 tests pass, `ruff`, `hglab sync --check`, `hglab kb validate`,
  `hglab config validate` and the secret scan all pass.

## Divergences from the spec and the live guide

Found by comparing the scaffold with the live `agent-guide.md` and read-only public
endpoints (no keyed call was made):

| Area | Scaffold | Reality | Action |
| --- | --- | --- | --- |
| `join_faction` | requires `name` | takes `faction_id` | fixed in validator, schema, docs |
| goal actions | no id parameter | `claim/confirm/cancel/abandon_goal` take `goal_id` | fixed |
| spam counter | matches events on `agent_id` | events carry `actor` (a name) | fixed in `limits.py` |
| `your_goals` | treated as a list | `{posted: [...], claimed: one or null}` | fixed |
| event paging | `before`/`has_more` | `next_before` | observatory accepts both |
| `give` | `to` or `x,y` | same, plus `insufficient_materials` when you lack items | docs only |
| islands | spec hopes for bridge-only land | the public terrain is one connected landmass | recorded as a kb claim |
| residents | spec mentions Quill | Quill and Quillwright, 17 structures, 3 open newcomer goals, no factions; by 16:50 UTC also Cairn (15 structures) and tide_scribe | kb goal updated |
| factions | open-join only | `found_faction` takes `membership` (`invite` default, `open`); new `invite name` action | validator, schema, docs, Fudgewright's bible |

Spec items not yet present in the scaffold: `analysis/` scripts, `hglab guide --refresh`
vendor copy (works, not committed), pinned action SHAs (still tags).

## What this session builds on

Personas are a layer over the existing loop, not a replacement. The role allowlist, lease,
validator, redaction, `HG_ENABLED` gate, kb conventions and `hglab sync` all stay and are
extended: personas add knobs the validator enforces, a persona-aware planner, influence
signals, the Pulse, per-agent workflows and five new skills. See
[personas and measurement](personas-and-measurement.md), [local play](local-play.md) and
[deploying an agent](deploy-agent.md).

## Public world facts used for planning

- Tick 3702, day 10 at 14:11 UTC on 2026-10-17; 2 agents; 17 structures; 0 factions.
- Terrain counts: deep water 7239, grass 4043, forest 1785, sand 1280, shallow water 1221,
  hills 647, mountain 169. Nodes: fiber 420, berries 393, wood 348, stone 130, ore 33.
- One walkable component (8-neighbour), so no island is reachable only by bridge.
- Candidate factory site, far from residents, sand beside shallow water with hills and wood
  within 8 tiles: around (89, 99). Candidate Neverland site, farthest grass from residents,
  shallow water and wood nearby: around (74, 112). Both are proposals for the navigators.

## What this session built (end of 2026-10-17)

- Personas: `agents/<slug>/persona.md` and `metrics.yaml` for wonka, mrs-bucket,
  grandpa-joe, tinker-bell, lost-boy, tootles and nibs; teams `chocolate-factory` and
  `neverland`; schemas `persona.json`, `metrics.json`, `team.json`; `config/agents.yaml`
  lists the seven identities, disabled.
- Code: `persona.py` (load, validate, knob enforcement), `mood.py` (four mood models,
  state in notebook key `persona_state`), `planner.py` (deterministic persona planner),
  `wake.py` (persona wake on top of `loop.run_wake`), `fixtures.py` (keyless client),
  `influence.py` (one function per signal), `measures.py` (named measures), `pulse.py`
  (gauges and reports), `judge.py` (review-route judge, budget-capped), `workflows.py`
  (caller generation), `data.py`, `cli_personas.py` (new commands).
- Workflows: `_agent.yml` plus seven generated callers; `agent-heartbeat.yml` retired;
  `scripts/publish_reports.sh` publishes to the `reports` branch.
- Skills: `hg-be-agent`, `hg-community`, `hg-new-agent`, `hg-pulse`, `hg-deploy-agent`.
- kb: the monument puzzle (`H-20261017-monument-buildable`), the P2 landmass claim with
  `analysis/landmass.py`, one goal per agent plus the ticket hunt, fifteen approach bets,
  two Strayling idea cards.
- Tests: 69 passing, fixtures only; `reports/examples` pinned by a snapshot test.
- Scaffold changes beyond the plan: embodied roles gained notebook bookkeeping
  (`remember`, `forget`), the builder gained `write`, the broker gained `whisper` and
  `write`; the validator accepts a `+`-joined set of hats so a persona can wear all of its
  roles in one wake unless `--role` pins one.

Still open: registering the names, confirming team territories in-world, the monument
hypothesis, the OpenAI review model id in `config/models.yaml`, the collective name in
`config/collective.yaml`, pinning action SHAs.
