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
- Found while verifying live (PR #33): the planner had judged walkability on the synthetic fixture
  map in the real world, so settlers asked for walks the world refused as `too_far`. Live wakes now
  read the public terrain from `/live/world.json`, every move target must be reachable within the
  12-step cap along walkable tiles, and upkeep in reach comes before any migration. Verified with
  three live work wakes for Fudgewright: a migration step and two roads at the factory site, every
  result accepted.

## 2026-10-18, 13:45 UTC: the land office acquires

- LandBroker's first goal is now land (PR #35). Each work wake stakes up to two free 5x5 lots with a
  claim sign on the lot's anchor (nearest first, a ring left around every other agent's hut; lot ids
  read F05-NW). One sale listing stands at today's price, base 5 wood, doubling at half the lots gone,
  ten times at a tenth free, capped at 50; it is cancelled and reposted when the price moves and may
  take a standing offer's goal slot. A paid sale deeds the buyer the lot they named by whisper or the
  unsold lot nearest their hut; the claim sign is rewritten with their name when the office passes.
  A 10x10 plot is four lots. The planner now counts storehouses out of view too (LandBroker had built
  three). A claim is a sign, a public record and the office's word, not a right the world enforces.

## 2026-10-18, 22:40 UTC: the verification outage

- From about 15:45 UTC every agent but LandBroker lost its daily verification and every scheduled
  job failed; LandBroker, registered that morning, was still verified. Three causes (PR #38): the
  challenge parser never read the game's plain key list ("with keys offer, total, motto and
  reversed"), so the structured-output schema had no properties and the model could only answer an
  empty object (the same fault made the automatic registration fail that morning); the keepalive
  took the lease before answering the challenge, and the lease is an action that answers 403 once
  verification lapses; a failed verify returns 403 verification_required with a fresh challenge in
  the body, which the code did not recognise.
- Now every live entry point observes and answers a pending challenge before taking the lease;
  arithmetic, Chebyshev distances, reversed words and letter counts are computed in code;
  quantities are typed as integers; word limits, quoted words, one-word answers and line counts are
  enforced before submission. All eight agents were re-verified from the workstation at 22:40 UTC
  (first attempt each) and the hourly keepalives renew verification from here.
- Two more faults surfaced by the first ticks after the fix (PR #40): a model plan that would
  disclose a private note now falls back to the deterministic plan and records why, instead of
  crashing the wake (a `remember` may restate a private note, its destination being private); and
  `publish_reports.sh` works in a separate git worktree while the pull skips `reports/examples`,
  after Clarion's publish step refused to switch branches over pulled example files.
- The observatory workflow had been copying `data/` into itself every hour, 33 levels deep on the
  `observatory` branch (PR #41); it now replaces the directory and drops the nest on restore.

## 2026-10-19/20: API 0.30.0 houses, and the collective learns to engage

- API 0.30.0 added blocks: 4x4 cells per tile, sixteen levels, wood, stone, thatch and metal at one
  item per four blocks, cube/slab/slope/door/window shapes, `place`, `remove` and `paint` within two
  tiles, 4096 blocks per agent. PR #43 gave every persona a `house` knob (size 1 or 3, a colour) and a
  deterministic plan around its hut: door, window, walls, roof, one step per wake as the pack
  affords it; a homing step carries the next step's material back when the hut is far; the
  validator counts a walled box the way the world does and keeps every box within two tiles.
- Day 70 showed a world that built alone: fifty-nine public lines named another agent once, no
  gives between strangers, no claims on peers' goals. This branch adds the engagement layer: a
  `stance` knob per persona (cooperative, neutral, competitive weights; MotherPail, Stoutheart and
  Fudgewright lean cooperative, GrandadPail and Tinkerglow competitive, the rest neutral) and one
  move toward another agent per wake when the observe offers one (`hglab.engage`, `_plan_engage`):
  a reply by name to whoever spoke near or stands near, a gift of spare materials within two tiles,
  a whisper of introduction or terms to the nearest agent anywhere (once a day per name), a claim
  on a peer's deliver-condition goal the pack can already fill (delivered by `_plan_deliver` in the
  next wakes), a contest line over a stranger's private structure inside the team's ground, salvage
  of a crumbling structure beside us, or one announced answering hit for a raid on our own
  structures. Only moves the worn hats allow are considered, so a builder gives and an envoy
  speaks; the stance picks among what is left. Collective members on other teams only ever hear
  cooperative or neutral words. The model-backed wake sees the same board and the stance in its
  guidance under ENGAGEMENT.
- Two rules of conduct found their edges on the way: a whisperer's name is a public identity, not
  private content, so an agent may answer them in the open (the disclosure check used to reject
  any say that named someone who had whispered us); and a public storehouse, a road, a bridge or a
  ruin on our ground is never contested. Unprovoked strikes on active peers' structures remain
  excluded: competitive means contesting land, prices and claims and answering a strike once.
- The first hour of live wakes on the engagement code (2026-10-20, 03:00 UTC) showed the moves
  landing (Clarion greeted Fudgewright by name in the open; Clarion, LandBroker and MotherPail
  whispered introductions to the nearest agents, Fairscale among them) and three faults. Every
  model-backed wake had failed with a 400 since the blocks fields joined the action schema (27
  optional parameters, the API allows 24): the six corner fields are now one `box` array the
  normaliser expands. The house window was refused as unsupported (a placement must reach level 0
  or touch a block): it now runs from the ground. Clarion's repeated invitations were refused (an
  invitation never expires, so a second one is `not_allowed`) and the refusal ended the round
  before the call and the notebook note: a refused invitation no longer stops the round, and
  agents already invited in the public record are never asked again.
- The second hour (04:40 UTC) showed the house loop and the gifts needing memory: a builder that
  woke out of view of its hut assumed no blocks stood and placed the door again (refused, every cell
  filled), so house progress is now counted from the observed position when the hut is in view and
  kept in the persona state otherwise; Lagalong gave berries to tide_scribe, a resident unseen for
  days, so engagement now reads every resident's last_seen_tick from the public snapshot and skips
  gifts and words to anyone unseen for a day and whispers to anyone unseen for three. Refused
  invitations are written into the collector's notebook state, so no agent is asked twice.
- The third hour (05:00 UTC) found the structural cause of the stalled building: every agent's
  pack stood at 45 to 50 of 50, mostly berries (20 to 42), every agent at 100 energy, so nobody
  ate and the gather step refused to run on a full pack; builds stalled, agents explored or rested,
  LandBroker roamed 45 tiles west of its office with no wood beside wood nodes. Pack hygiene now:
  berries above fifteen are shed (eaten when energy has room, deposited in an own storehouse along
  with other surplus), berries are no longer the filler once fifteen are held, a farm is left to
  hold its berries when the pack already carries thirty, and when nothing wanted is in view the
  agent walks toward the nearest node the public snapshot knows (`_plan_forage`). The Exchange has
  a home at the land office hut (71, 65), so its shifts walk back when far and idle.
- The fourth hour (05:50 UTC): the slimmed schema still failed with "Schema is too complex", so
  the block fields left the model's action schema altogether (fifteen optional parameters, the
  shape that compiled before the blocks arrived); the deterministic house plan lays the blocks.
  The first hygiene rules were too polite for agents that sit at 100 energy every wake, so a pack
  that is full with more than twenty-five berries now eats two a wake regardless, deposits go into
  any storehouse of ours (own, a teammate's, the collective's), and a full pack walks toward the
  nearest such storehouse within forty tiles. Neverland owns no storehouse yet; its agents eat.
- Hours five and six (06:00 to 07:10 UTC): the world refuses a meal at full energy and a refused
  first action ends the batch, so meals are sized to the energy room again and the storehouse walk,
  the forage, the migration and the homing run when no move is planned yet, so a word may precede
  them; a far-from-home wake that already spoke keeps its label and walks after the word. The plan
  schema was proved to compile with one real model call. The live records then showed the whole
  loop turning: model wakes answering again (LandBroker's wake spoke and built a sign), MotherPail
  depositing twenty-two berries into her storehouse and her pack falling from forty-eight to
  twenty-six, harvests and gathering trips resuming, Clarion building roads, gifts and words by
  name between the teams, Tinkerglow's window standing. The harvest is capped so a pack never
  refills with berries past thirty, and gifts are judged from where the agent will stand.

## 2026-10-20, 07:40 UTC: the competitive footing, reclaiming and the Neverland border

- The owner set the collective on a competitive footing: the holdings of residents unseen for two
  days or more are reclaimed (demolished for the quarter the world drops as a cache, 5 energy and
  10 damage a hit, announced once in the open and stopped if the owner returns and speaks); nobody
  seen within two days is struck first and collective members never are. Every persona carries a
  `reclaim` knob; the builder and experimenter hats may demolish; stances lean competitive.
- Neverland's territory is confirmed (a circle at (74, 112), radius 10, the sea to the south) and its
  border is eight riddle signs on the north ring and the two flanks, raised nearest-first by any
  member carrying wood, with one opening on the east ring at (84, 105). Tinkerglow is the
  gatekeeper: she whispers the opening to any visitor she finds within fourteen tiles of the
  centre, once a day per name. Stoutheart and Tinkerglow put the team's storehouse first.
- First live hour on the competitive code (13:00 to 13:40 UTC): Strayling struck Quill's storehouse
  at (67, 55) three times (80 to 50 hp) after the announcement, Lagalong walked to join him,
  Stoutheart raised the third border sign at (79, 102) and a wall inside the ring, LandBroker staked
  five more lots. Clarion's walk toward Cairn's storehouse was refused as too_far four times: the
  world's move budget is a cost of 12 with hills at 2 and roads at 0.5, and the reachability search
  had counted every tile as 1 and allowed a route to end on the storehouse itself. The search now
  prices hills and roads, structures beyond the view count (bridges, walls, and the huts, stores,
  towers and monuments a route stops beside), and a trip step never lands on a structure. Those who
  keep inside their ground only carry a full pack to a storehouse near it, which ends Tinkerglow's
  walk out toward the Chocolate Factory's store and back.
- Second competitive hour (13:40 to 14:35 UTC): Strayling tore down Quill's storehouse at (67, 55)
  and looted it, Lagalong laid a road on the cleared tile and banked ten stone in the land office's
  vault, Tinkerglow and Stoutheart raised the first, sixth and seventh riddle signs (four of eight
  stand), LandBroker staked five more lots. Clarion reached Cairn's storehouse but spent the wake on
  a road, since the reclaim came after the build and its four actions no longer fitted; the reclaim
  now comes before the ordinary build, sizes its hits to the actions left, and picks the nearest
  band of eight tiles before the richest target, so the cast no longer converges on one store. An
  accepted step now spends the pack the later steps plan with, which ends deposits of stone a road
  had already used.
- Third competitive hour (14:40 to 15:30 UTC): all eight riddle signs stand (Tinkerglow raised the
  first two, Stoutheart the rest), Lagalong took Quill's tower at (69, 57) from 100 to 30 hp after
  the announcement, Clarion joined him, LandBroker staked six more lots. Three inefficiencies fixed:
  inside-keepers oscillated between a reclaim expedition and the walk home, so an expedition now
  holds the migration while a target is in range, and the gatekeeper and the storekeeper reclaim
  only near Neverland (`reclaim.range`); a gift to a teammate whose pack was full was refused first
  and ended the batch before the hits, so a gift goes last when the batch does not move; a deposit
  was sized from the wake's start position rather than where the agent stands after its moves.
- Fourth competitive hour (15:30 to 16:25 UTC): Lagalong tore down Quill's tower at (69, 57),
  Clarion and Lagalong tore down Bishop's storehouse at (76, 62) the day Bishop crossed the two-day
  line, Strayling has Cairn's storehouse at (73, 70) down to 20 hp, LandBroker staked six more lots.
  Gifts between collective members were refused seven times as inventory_full, so gifts go to
  strangers only. Stoutheart sat at a full pack unable to carry the stone for Neverland's store,
  since the world refuses a meal at full energy and every wake starts full: a full pack now eats one
  berry at the end of a batch that moved, when the walk has spent the energy the meal restores.
