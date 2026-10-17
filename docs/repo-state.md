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
| residents | spec mentions Quill | Quill and Quillwright, 17 structures, 3 open newcomer goals, no factions | kb goal updated |

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
