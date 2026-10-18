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
| monument | 60 items vs a 50 pack, so maybe impossible | Cairn built one at (71,70) at tick 4637, 32 ticks after a storehouse two tiles away | hypothesis H-20261017-monument-buildable supported at P1 |
| world | two residents | by tick 5740: Quill, Quillwright, Cairn (86 structures, faction Wayfarers, open), Bishop, tide_scribe, Hinterlands, plus our seven | digest shows them each wake |

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

## Later on 2026-10-17: live, talking, and busy

- All eight identities registered (Fudgewright, MotherPail, GrandadPail, Tinkerglow,
  Stoutheart, Strayling, Lagalong, and the town crier Clarion in team `square`); every
  `HG_AGENT_<NAME>` is on and `HG_ENABLED` is true, so the schedules run on `main`.
- Model mix and spend caps (`config/models.yaml`, `config/budget.yaml`,
  `hglab budget status --project`): Haiku 5.5 for routine wakes and shift lines, Sonnet 5.5
  for the talkative navigators, the crier, the judge and challenges; about $21 a month.
- Structured outputs rejected the first plan schema; the model now gets a compact action
  shape that is expanded before validation, and model errors are recorded, never swallowed.
- Every model-backed wake reads an environment digest built the way the site's feed is
  filtered (All, Building, Trade & Goals, Talk, Factions) and may return a journal note and
  adaptation proposals for the weekly retro.
- Work shifts (`knobs.work`) keep agents building between character wakes with the
  deterministic planner; each run ends with one public line so the Talk filter shows every
  agent alive. GrandadPail's lines are the loud, self-satisfied register of the grandfather
  the internet loves to resent, PG-13 and never aimed at a peer.
- Clarion watches the game's public surface (API version, guide tables, event and structure
  types, factions, residents) and announces what changed; `hglab world watch` does the same
  for humans and can file idea cards.
- Monument puzzle answered from the public log: build draws on an adjacent own storehouse.
- Owner's standing instruction from this evening: merge PRs whose checks pass, test new
  agents locally end to end, then promote them to scheduled Actions.

## Night of 2026-10-17/18: the game moved to API 0.19.0

- Hinterglass added `reject_claim` (a poster ends a claim without paying; public
  `goal_rejected` event), claims that lapse 720 ticks after they are made, and the observe
  fields `since_last_observe`, `events_omitted` with `events_next_after`, and `worth_doing`.
  Adopted in PR #21: the navigator and broker hats may reject a claim, the digest files
  `goal_rejected` under Trade & Goals, and the planner prompt treats `worth_doing` and
  `hints` as the game's suggestions, not orders.
- Clarion's scheduled tick and shift then hung in silence until the job timeout. Root cause:
  his notebook feature snapshot grew past the 2000-character state limit and
  `mood.dump_state` halved a one-entry visited history to itself forever. PR #20 makes the
  serializer trim in a fixed order where every step removes something, slims the snapshot
  (arrivals from the resident count, 8-character row digests), runs every wake under a
  faulthandler watchdog (jitter plus ten minutes: a stall prints every thread's stack and
  exits non-zero), logs phase markers in scheduled ticks, and drops the tick job timeout to
  30 minutes.
- Shift announcements: the compose prompt names the numeric character limit and over-long
  lines are trimmed at a sentence instead of falling back to the template (PR #19).
- Verified: Clarion's wake on the fixed code ran live from the workstation and announced the
  version jump in the Talk feed (tick 7319); the seven others kept building and talking on
  schedule through the night.

## 2026-10-18, early: API 0.22.0 and the collector programme

- The game moved on to API 0.22.0 (goals with a self-confirming `condition`, only the three
  oldest farms grow, published rate limits, more public reads); PR #23 aligned the planner,
  validator, docs and skills.
- Clarion is now the community's collector of bugs and feature requests for the makers (PR
  #24): the ledger `config/requests.yaml` holds requests and themes; `hglab crier round`
  founds the theme faction a persona owes, posts one escrowed goal per open request, confirms
  a claimant's public or whispered feedback, and makes one hourly call naming residents. The
  shift job runs it as its own step. Live: factions #2 Blueprint Science (Clarion) and #3
  Readable Replay (Lagalong), goals #5 (replay stacks say lines) and #6 (an action to propose
  new blueprints with periodic-table materials). The world allows one faction per agent, so
  membership is the first vote and a public line naming a second theme is the second.
- Every embodied hat may join or leave a faction; the planner prompt shows each agent the
  board and asks it to argue its preference fairly. Peers may be named in public to invite,
  ask or thank them, never to mock.

## 2026-10-18, 02:00 UTC: LandBroker, the land office

- A ninth agent, LandBroker (`agents/land-broker`, team The Exchange, agent 16), made with the
  hg-new-agent skill from one answers file and registered the same hour (PR #28). It surveys the
  world in 10x10 plots, registers a plot for a posted fee of 5 wood (collective members give the fee
  into the vault; outsiders claim the registration goal, which confirms itself on delivery),
  announces each deed, keeps the registry in its public profile and on deed signs, buys surplus
  through deliver-condition offers, and banks what it is given in a private storehouse toward
  lending. The ledger is `config/plots.yaml`; `hglab land board|round|validate` drive it; the
  shift job runs the round as its own step. Every collective agent's work shift now deposits
  surplus into an adjacent vault.
- Phases: survey and registry now; brokerage (seller demolishes, buyer builds, the office takes a
  share) when free plots fall below half; lending against deeds when the vault passes 200 items.
  New phases arrive as retro proposals, never as the agent editing its own files.
- First lines in the feed at ticks 8019 and 8024: the survey count and the coming fee; wood
  gathered toward the vault.

## 2026-10-18, 11:00 UTC: API 0.26.2 and faction visibility

- The theme factions never vanished; the site's Factions filter shows only the newest 300 public
  events and the foundings had aged out. Every collector round now sends up to two invitations by
  name into the sender's theme faction (PR #30), so the themes stay in the feed; Clarion announced it.
- API 0.26.2 (PR #31): every building or surveying hat may `repair`; the work-shift planner mends the
  most damaged own structure in reach before building, takes berries from own farms once they hold
  12 or more, and takes salvage from adjacent caches and ruins. Storm days double the per-tile move
  estimate; the digest carries the day's season and weather; every prompt explains rain, drought,
  storm and winter. The site shows an agent dozing after 30 minutes without an observe, so each
  caller's keepalive runs hourly, 8 minutes after its work shift ends (no gap over 27 minutes).
