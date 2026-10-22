# Plan: a distributed ecosystem of NemoClaw hosts with routable agent and human skills

The aim, in plain words: many agents (and people) with different data and tools, each running on
whatever hardware is at hand, each measured the same way, discoverable in one place, so that a task
goes to whoever does that kind of work best right now. The hosts stay independent and may be
switched off; the record of what they can do and how well they did it survives in one project.

This plan builds on what runs today ([reference-architecture.md](reference-architecture.md)) and
ends with the cut-over from GitHub Actions. Each phase has a deliverable that can be shown working
before the next starts.

## Phase 0: what exists (2026-10-22)

- `hglab local`: supervisor, memory graph with per-wake performance, A2A cards and task board,
  MCP server, status page, one-command start and a logon service.
- NemoClaw on this host: sandbox `hinters`, OpenClaw, local Ollama and the Anthropic route.
- Measurement: graph performance per persona and model; Pulse per persona and team.
- Backups: graph snapshots on the host only.

## Phase 1: cards, backups and the page (this repository, no cloud)

Deliverables:

- `hglab local cards [--write]`: the capability card of every persona (section 4.1 of the reference
  architecture), derived from the persona, its role charters (`roles/*.md`: mission, allowed actions,
  skills, outputs), the world and local tools, the datasets it reads, its performance by model from
  the graph, and its backup state. Written to `runs/local/cards/<slug>.json`.
- `hglab local backup push|list [--target local:<dir>|gs://bucket/prefix]`: a tarball of
  `config/local.yaml`, `runs/local/status.json`, the supervisor log and a fresh graph snapshot,
  named `<host_id>-<utc>.tar.gz`, pushed to the target. The GCS target uses `gcloud storage cp`
  from the installed SDK; the local target needs nothing.
- `config/local.yaml` gains `ecosystem: {host_id, data_boundary, backup_target}`.
- The status page shows, per persona: advertised capabilities (roles, skills, tools, datasets),
  performance by model, and backups (snapshots and pushed backups with their times).

Acceptance: cards validate as A2A agent cards; a backup pushed to a local directory restores on a
clean checkout; the page shows all three blocks for all nine personas.

## Phase 2: one GCP project, publish and restore

GCP resources (one project, one region):

| Resource | Purpose | Notes |
| --- | --- | --- |
| GCS bucket `<project>-hinters-ecosystem` | the shared record | uniform access, versioning on, 90-day retention on `backups/`, lifecycle to Nearline after 30 days |
| Service account per host `host-<id>@` | the host's only credential | roles: object creator and viewer, with an IAM condition restricting writes to `hosts/<id>/*` and `agents/<slug>/*` for that host's slugs; key stored in the host keyring |
| Cloud Run service `ecosystem-monitor` | reads the bucket, builds the index, answers routing and assessment queries, serves the ecosystem page | no inbound to hosts; read-only on the bucket plus write to `registry/` and `routing/` |
| Cloud Scheduler | rebuild the index every 5 minutes; nightly assessments | calls the monitor |
| BigQuery dataset `hinters` | external tables over `agents/*/performance/*.json` and `teams/*/assessment/*.json` | cross-host queries, no ETL |
| Cloud Logging sink | OCSF audit lines from each sandbox, shipped by the host | optional in phase 2 |
| Secret Manager | monitor's signing verification keys, host public keys | hosts never read it |

Bucket layout:

```text
hosts/<host_id>/card.json                  host card: hardware, runtime versions, agents, boundary
hosts/<host_id>/heartbeat.json             every 5 minutes: utc, supervisor state, stack status
hosts/<host_id>/backups/<utc>.tar.gz       config, status, log, graph snapshot
hosts/<host_id>/inbox/<task_id>.json       A2A message envelopes addressed to this host's agents
agents/<slug>/card.json                    capability card, signed
agents/<slug>/performance/<utc>.json       daily extract from the graph
agents/<slug>/snapshots/<utc>.sqlite       graph snapshot (host-scoped graphs contain only that host's agents)
agents/<slug>/records/<date>/<run_id>.json redacted wake records (what the reports branch holds today)
teams/<slug>/assessment/<utc>.json         Pulse and goal maturity per team
humans/<id>/card.json                      a person's skill card, published by the person
registry/index.json                        built by the monitor: all cards, freshness, boundary
routing/decisions/<utc>.jsonl              every routing answer with its evidence
```

Deliverables:

- `hglab local publish`: card, heartbeat and performance extract to the host prefix; runs from the
  supervisor loop every 5 minutes and after every wake.
- `hglab local backup pull [--host <id>]`: restore the latest backup and snapshot on a fresh host.
- The monitor, minimal: a Cloud Run service with two routes, `GET /index` and `GET /agents/<slug>`,
  and a page listing hosts, agents, freshness, performance and backups.
- Bootstrap script `scripts/bootstrap-host.sh` (Linux) that performs section 7 of the reference
  architecture up to `hglab local up`, pulling the host's backup first.

Acceptance: a second host (the new hardware) bootstraps from the bucket, appears in the index within
five minutes, and its agents' wakes show in BigQuery the next day.

## Phase 3: routing, mailboxes and people

Deliverables:

- `POST /route` on the monitor: a task description with required skills, datasets, tools and
  boundary; the answer is a ranked list with evidence. Scoring as in section 4.2 of the reference
  architecture; weights in a config file in `registry/`.
- Mailboxes: the supervisor polls `hosts/<id>/inbox/`, moves each envelope onto the local task
  board, and the persona's next wake reads it as it reads A2A tasks today; outcomes are published.
- `hglab local route "<task>"` and the MCP tool `route`, so an operator in Claude Code or the
  NemoClaw sandbox can ask the ecosystem who should do something and send it.
- Human skill cards: a short form (the same `x-collective` block) published by a person under
  `humans/<id>/`; routing treats a person like an agent whose mailbox is a notification.
- Signatures: each host signs what it publishes with an ed25519 key generated at bootstrap; the
  monitor verifies and marks unsigned cards as unverified.

Acceptance: a routing query for a land survey returns LandBroker first with its evidence; a task
written to the mailbox of the other host is completed by its persona and the outcome appears in
the index.

## Phase 4: assessment and iteration

- Team assessments: Pulse plus goal maturity (targets revised by retrospectives and the history of
  those revisions) published nightly.
- Routing weights tuned from `routing/decisions/` outcomes; the monitor reports when a capability's
  advertised performance drifts from its measured performance.
- The ecosystem page shows, per agent: advertised capabilities and tools, measured performance per
  capability, backups and their freshness, and the tasks routed to it with their outcomes.

## Cut-over from GitHub Actions

Criteria, per persona, before `HG_AGENT_<NAME>` is switched off on Actions:

1. Seven consecutive days of local wakes with no failed job in `runs/local/status.json`.
2. The persona's Pulse over those seven days is not worse than its previous seven on Actions.
3. A backup pushed from the host restores on another machine (tested once per host).
4. The host heartbeat has not been stale for more than 15 minutes in that week.
5. The lease shows no double runs (the world's notebook lease is the arbiter either way).

Order: Clarion, then LandBroker, then the Chocolate Factory, then Neverland. Actions stays as the
fallback runtime: the workflows remain, disabled by variable, and can be re-enabled per persona.

## New hardware: the bootstrap contract

Any new runtime must come up the same way, so that a coworker can repeat it:

1. Base OS and network; the inventory table from [local-runtime-setup.md](local-runtime-setup.md).
2. `curl -fsSL <repo>/scripts/bootstrap-host.sh | bash -s -- --host <id>`: installs prerequisites,
   clones the repository, creates the virtual environment, installs NemoClaw unattended with the
   provider that fits the hardware.
3. A person enters the keys by name (world identities for the personas this host will own, the model
   key if hosted inference is wanted, the host service account).
4. `hglab local backup pull --host <id>` restores state; `hglab local up` starts; `hglab local
   service install` makes it survive reboots; `hglab local publish` announces it.
5. The monitor shows the host; the cut-over criteria apply before Actions is switched off for the
   personas it owns.

## Open questions for the team

- Boundary vocabulary: three levels (`public`, `internal`, `restricted`) or the enterprise's own.
- Whether human cards should be self-published or come from an HR skills system of record.
- Inbound tasks for hosts that can accept them (a Cloud Run proxy to the host's A2A server over a
  tunnel) versus mailbox-only for everyone; mailbox-only is simpler and is the proposal.
- Cost ceiling for hosted inference per host per month, and whether routing should weigh cost.
