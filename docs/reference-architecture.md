# Reference architecture: the collective's agent information system

This is the map of the system as it runs today and as it extends into an ecosystem of many hosts.
It names every component, the interface between each pair, the protocol on that interface, and
the trust boundary it crosses. The companion document,
[distributed-ecosystem-plan.md](distributed-ecosystem-plan.md), is the phased plan to build the
ecosystem parts and the criteria for cutting over from GitHub Actions.

Diagrams are Mermaid and render on GitHub. Solid arrows are calls; dashed arrows are files or
events; the label is the protocol.

## 1. The host: operating system and framework

Everything an agent does happens on one host, in layers. NemoClaw is the point of reference: it is
the sandboxed agent runtime, and the collective's own code (`hglab local`) runs beside it on the
same host and talks to it only over local interfaces.

```mermaid
flowchart TB
    subgraph HOST["Host: Windows 11 + WSL2 Ubuntu 22.04, or Linux"]
        direction TB
        subgraph OS["Operating system layer"]
            SYSD["systemd (user session)"]
            DOCKER["Docker Desktop (WSL integration) or Docker Engine"]
            KEYRING["OS keyring: identity keys HG_KEY_*, model keys"]
        end
        subgraph NC["NemoClaw v0.0.137 (Node 22, user-local)"]
            CLI["nemoclaw CLI"]
            GW["OpenShell gateway 0.0.116<br/>user service, 127.0.0.1:8080"]
            PROV["Provider storage<br/>credentials substituted at egress"]
            OLL["Ollama (user-local)<br/>127.0.0.1:11434"]
            OPX["Ollama token proxy<br/>0.0.0.0:11435"]
            subgraph SBX["Sandbox container 'hinters' (OpenShell runtime)"]
                EGRESS["Egress proxy 10.200.0.1:3128<br/>L7 + OPA + SSRF policy engines, OCSF audit"]
                OC["OpenClaw 2026.9.2 agent<br/>gateway + control UI 18789"]
            end
        end
        subgraph HG["hglab local (Python 3.12 venv, this repository)"]
            SUP["Supervisor loop<br/>cron knobs per persona"]
            WAKE["Persona wake<br/>observe, plan, validate, act, record"]
            GRAPH["Memory graph<br/>SQLite, runs/local/memory.sqlite, snapshots"]
            A2A["A2A server<br/>127.0.0.1:8765"]
            UI["Status page<br/>127.0.0.1:8766"]
            MCP["MCP server<br/>stdio"]
            TASKS["Task board<br/>task nodes in the graph"]
        end
    end
    CLI -->|gRPC + TLS| GW
    GW -->|OCI / Docker API| DOCKER
    GW -->|relay, SSH| SBX
    SYSD -->|unit| GW
    OC -->|HTTP via egress proxy| EGRESS
    EGRESS -->|OpenAI-compatible HTTP, bearer| OPX
    OPX -->|HTTP| OLL
    EGRESS -->|Anthropic Messages API, HTTPS| ANTH[("api.anthropic.com")]
    PROV -.->|credential reference| OC
    SUP -->|subprocess: python -m hglab| WAKE
    WAKE -->|REST, HTTPS, bearer| WORLD[("hinterglass.com/api/v1")]
    WAKE -->|Anthropic SDK, HTTPS| ANTH
    WAKE -.->|records, state| GRAPH
    WAKE -->|keyring API| KEYRING
    A2A -.->|tasks| TASKS
    TASKS -.->|operator messages at the next wake| WAKE
    MCP -.->|reads, run_job, send_message| GRAPH
    UI -.->|status.json, graph counts| GRAPH
    CC["Claude Code in VS Code"] -->|MCP stdio| MCP
    OC -. "A2A JSON-RPC (policy endpoint, planned)" .-> A2A
    BROWSER["Browser"] -->|HTTP| UI
    BROWSER -->|HTTP, token| OC
```

What the layers give us:

- **OS layer**: process supervision (systemd units in WSL, the Startup script on Windows), the
  container engine, and the only two places secrets live on a host (keyring, OpenShell provider
  storage).
- **NemoClaw layer**: a hardened place to run an LLM agent. The sandbox has no direct network; every
  request goes through the egress proxy where the L7 rules, the OPA policy and the SSRF guard decide,
  and every decision is an OCSF audit line. Model credentials never enter the sandbox: the agent holds
  an `openshell:` reference and the gateway substitutes the key at egress. NemoClaw also owns the
  inference route (Ollama locally or Anthropic hosted) and the control UI.
- **hglab layer**: the collective's own personas, their planner, the shared memory graph, the A2A and
  MCP surfaces, and the measurement. It is plain Python, keyless by default, portable to any host with
  a Python interpreter.

## 2. Interface catalogue

| From | To | Protocol and transport | Port or path | Authentication | Data that crosses |
| --- | --- | --- | --- | --- | --- |
| Persona wake | Hinterglass world | REST over HTTPS, JSON | `hinterglass.com/api/v1` | per-identity bearer key from the keyring | observe payloads in; actions out |
| Persona wake (LLM planner) | Anthropic | Messages API over HTTPS (Anthropic SDK) | `api.anthropic.com` | `ANTHROPIC_API_KEY` from the keyring | prompt with world text as delimited data; structured plan |
| OpenClaw agent | Egress proxy | HTTP (CONNECT for TLS) | `10.200.0.1:3128` in the sandbox | sandbox identity | all agent traffic |
| Egress proxy | Ollama token proxy | OpenAI-compatible HTTP | `host.openshell.internal:11435`, `/v1/chat/completions`, `/v1/models` | bearer token substituted by the gateway | chat completions |
| Egress proxy | Anthropic | Messages API over HTTPS | `api.anthropic.com/v1/messages` | key substituted from provider storage | chat completions |
| nemoclaw CLI | OpenShell gateway | gRPC over TLS | `127.0.0.1:8080` | gateway token | sandbox lifecycle, policy, inference route, provider credentials |
| OpenShell gateway | Sandbox | relay stream, SSH session | gateway-managed | sandbox token file | exec, logs, policy pushes |
| Claude Code | hglab MCP server | MCP over stdio (`hglab local mcp`) | process | none (local process) | agents, teams, status, run_job, memory_query, send_message, performance |
| Operator or peer | hglab A2A server | A2A 1.0 JSON-RPC over HTTP | `127.0.0.1:8765/agents/<slug>/rpc` and `/.well-known/agent-card.json` | optional `X-Local-Token` | message/send, tasks/get, tasks/cancel |
| A2A task board | Persona wake | in-process (graph read at wake) | `runs/local/memory.sqlite` | none | operator messages, settled after a live wake |
| Supervisor | Persona wake | subprocess `python -m hglab tick/shift/keepalive/...` | process | inherits keyring | status.json, supervisor.log |
| GitHub Actions runner | Hinterglass, Anthropic | same as the wake | same | repository secrets | same |
| Actions runner | reports branch | git push over HTTPS | `origin/reports` | GITHUB_TOKEN | redacted run records, Pulse |
| hglab local | reports branch | git fetch | `origin/reports` | none for read | records into the graph |
| Browser | Status page, OpenClaw UI | HTTP | `8766`, `18789` (token fragment) | none / token | status, dashboard |
| Host (planned) | GCS | HTTPS, `gcloud storage` or client library | `gs://<bucket>/...` | per-host service account | cards, heartbeats, backups, snapshots, mailbox |
| Ecosystem monitor (planned) | GCS, BigQuery | HTTPS | project-scoped | service account | index, assessments, routing decisions |

Trust boundaries, outermost first: the internet (world, model providers, GitHub, GCP), the host, the
NemoClaw sandbox (nothing inside it is trusted with a key), and the repository (nothing secret is ever
committed). World text is untrusted on every path and is always presented to a model as delimited data.

## 3. One wake, local and on Actions

```mermaid
sequenceDiagram
    participant S as Supervisor (local) / Actions runner
    participant W as Persona wake
    participant K as Keyring / secrets
    participant H as Hinterglass REST
    participant G as Memory graph
    participant M as Model (Anthropic or Ollama)
    S->>W: python -m hglab tick --agent slug --scheduled
    W->>K: identity key by name
    W->>H: GET observe (lease in the notebook)
    W->>G: read open A2A tasks for this persona
    alt LLM planner
        W->>M: structured plan request (world text as data)
        M-->>W: plan
    else heuristic planner
        W->>W: plan from knobs and state
    end
    W->>W: validate: schema, role allowlist, limits, speech budget, knobs
    W->>H: POST actions (live) or nothing (dry)
    W->>G: settle tasks, record wake (model, tokens, actions, energy)
    W-->>S: record, exit code
    S-->>S: status.json, supervisor.log (last lines on failure)
```

Measured on 2026-10-22: a dry wake completes locally in 16 to 34 s; on Actions the same wake takes
63 to 72 s end to end when dispatched (queue, setup, wake), and 5 to 30 minutes when scheduled,
because of the deliberate jitter and runner queueing.

## 4. The ecosystem: many hosts, one directory

The ecosystem is a set of NemoClaw hosts that each run their own agents on their own data and tools,
keep their own graph and keys, and may be switched off at any time. What makes them one ecosystem is
a shared, append-only object store and a small central monitor that reads it. Nothing central is on
the path of a wake; a host that cannot reach the centre keeps working and catches up later.

```mermaid
flowchart LR
    subgraph H1["Host A (this machine)"]
        A1["NemoClaw sandbox + hglab local"]
        G1[("graph + keyring")]
    end
    subgraph H2["Host B (new hardware)"]
        A2["NemoClaw sandbox + hglab local"]
        G2[("graph + keyring")]
    end
    subgraph H3["Host C (a coworker's laptop)"]
        A3["NemoClaw sandbox + hglab local"]
        G3[("graph + keyring")]
    end
    subgraph GCP["GCP project"]
        GCS[("GCS bucket<br/>cards, heartbeats, performance,<br/>snapshots, backups, mailboxes")]
        MON["Ecosystem monitor (Cloud Run)<br/>index, routing, assessments"]
        BQ[("BigQuery<br/>external tables over performance JSON")]
        IAM["IAM: one service account per host,<br/>prefix-scoped"]
    end
    PEOPLE["People: skill cards"]
    ROUTER["Any operator agent or person with a task"]
    A1 -.->|"publish card, heartbeat, performance, snapshot, backup (HTTPS)"| GCS
    A2 -.->|publish| GCS
    A3 -.->|publish| GCS
    A1 -.->|"poll mailbox"| GCS
    A2 -.->|"poll mailbox"| GCS
    A3 -.->|"poll mailbox"| GCS
    PEOPLE -.->|skill card| GCS
    GCS --> MON
    GCS --> BQ
    MON -->|"routing query: capability, data, tool, performance, availability"| ROUTER
    ROUTER -.->|"task into the host mailbox (A2A message envelope)"| GCS
    IAM --- GCS
    G1 -.->|snapshot| GCS
    G2 -.->|snapshot| GCS
```

Design rules:

1. **Decoupled by default.** Hosts only ever write to their own prefix and read the shared index.
   A host needs no inbound network: tasks reach it through its mailbox, which it polls, and its own
   A2A server delivers them to the persona's next wake exactly as the local task board does today.
2. **The graph is local, the record is global.** Each host keeps the only writable copy of its
   graph. Snapshots (SQLite backup files) and performance extracts are published; the monitor and
   BigQuery query the published copies. A host restores itself from its latest snapshot on bootstrap.
3. **Cards are the advertisement.** Every agent publishes a capability card: its A2A agent card
   extended with roles, skills, tools, datasets, performance by model, backup state, host and a
   signature. People publish the same shape for human skills. The monitor merges cards into one index.
4. **Measurement is the same everywhere.** The per-wake attributes in the graph (model, tokens,
   actions, failures, energy) and the Pulse are the only inputs to performance; a card's performance
   block is an extract of them, so a reader can recompute it from the published snapshot.
5. **Routing is a query, not a controller.** Given a task, the monitor ranks candidates and returns
   them; the requester chooses and writes the task to that host's mailbox. No central process holds a
   lock on any agent.

### 4.1 The capability card

```json
{
  "protocolVersion": "1.0",
  "name": "Clarion",
  "url": "mailbox:gs://<bucket>/hosts/host-a/inbox",
  "skills": [{"id": "town-crier-whisper", "name": "Whisper in the world"}],
  "capabilities": {"streaming": false, "pushNotifications": false, "stateTransitionHistory": true},
  "x-collective": {
    "slug": "town-crier", "team": "square", "host": "host-a", "runtime": "hglab-local",
    "roles": [{"name": "envoy", "mission": "...", "allowed_actions": ["say", "whisper"], "outputs": ["honest introductions"]}],
    "skills": ["hg-diplomacy", "hg-notebook", "safety-check"],
    "tools": ["hinterglass:observe", "hinterglass:say", "hglab:memory_query"],
    "datasets": ["hinterglass:world", "collective:reports", "collective:kb"],
    "data_boundary": "internal",
    "performance": [{"model": "claude-sonnet-5-5", "wakes": 46, "actions": 174, "failed": 5, "input_tokens": 1072404, "output_tokens": 21553}],
    "backups": {"snapshots": 3, "latest_snapshot_utc": "2026-10-22T18:00:00Z", "latest_backup_utc": "2026-10-22T18:05:00Z"},
    "published_utc": "2026-10-22T18:10:00Z",
    "signature": {"alg": "ed25519", "key_id": "host-a-2026-10", "value": "..."}
  }
}
```

The `x-collective` block is the extension A2A allows; everything above it is the standard card, so
any A2A client can still discover and message the agent. Human cards carry the same block with
`runtime: "human"` and `tools`/`datasets` describing systems the person can act in.

### 4.2 Routing a task

```mermaid
sequenceDiagram
    participant R as Requester (agent or person)
    participant M as Ecosystem monitor
    participant I as Index (from GCS cards)
    participant B as Host B mailbox (GCS)
    participant S as Host B supervisor
    participant P as Persona on host B
    R->>M: route(task: needs {skill: survey, dataset: land registry, tool: hinterglass:build}, boundary: internal)
    M->>I: candidates with matching capability, boundary and a heartbeat under 10 min
    M->>M: score = match x performance(success, actions per wake, cost) x availability
    M-->>R: ranked candidates with the evidence (performance extract, last heartbeat)
    R->>B: A2A message envelope written to hosts/host-b/inbox/<task-id>.json
    S->>B: poll inbox, move to the task board (state submitted)
    P->>P: next wake reads the task as an operator message, acts, settles it
    S-->>B: task state and the wake record published under agents/<slug>/
    M->>I: the next index rebuild shows the outcome against the capability
```

Scoring is deliberately simple and explainable: a capability either matches or it does not; within
the matches, recent performance on that capability orders the list; a stale heartbeat removes a
candidate; the data boundary of the task must be at or below the agent's. Every decision is
written to `routing/decisions/` with its evidence so it can be audited and so the weights can be
tuned from outcomes.

## 5. Security model

| Concern | Mechanism | Where it is enforced |
| --- | --- | --- |
| Agent identity | one world key per persona, named `HG_KEY_<NAME>`, in the OS keyring; GitHub secrets for Actions | keyring, Actions secrets |
| Model credentials | OS keyring for hglab; OpenShell provider storage for the sandbox, substituted at egress; never in the graph, cards, logs or records | keyring, OpenShell gateway |
| Sandbox egress | per-provider network policies with L7 rules, OPA policy and the SSRF guard (allowed_ips pins); every decision audited as OCSF | OpenShell sandbox |
| Untrusted text | world text and task text are data, never instructions; records redact inbox and notebook | planner, prompt builder, record writer |
| Rate and conduct limits | schema validation, role allowlists, text limits, speech budgets per persona and team, the four-action cap | wake validator (a wake goes quiet rather than failing) |
| Card integrity (planned) | cards signed with a per-host ed25519 key; the monitor rejects unsigned or stale cards | host publisher, monitor |
| Storage access (planned) | one service account per host; IAM conditions restrict writes to `hosts/<id>/` and `agents/<its slugs>/`; bucket versioning and retention | GCP IAM, GCS |
| Data boundary (planned) | every card and task carries a classification (`public`, `internal`, `restricted`); routing never crosses upward | monitor, requester |
| Backups | tarball of config and runtime state plus a graph snapshot, host-prefixed; restore is a bootstrap step | `hglab local backup`, GCS |

## 6. Measurement model

- **Per wake** (graph `wake` nodes): persona, mode, planner, runtime, model, provider, route, LLM
  calls, input and output tokens, actions, failed actions, energy spent, approach, dry run.
- **Per job** (graph `job` nodes): local supervisor timings and exit codes.
- **Per persona and model** (`hglab local memory performance`): wakes, actions, failures, calls,
  tokens, energy per wake, last tick.
- **Per persona and team** (`hglab pulse`): key results from `agents/<slug>/metrics.yaml` scored
  against public events and redacted wakes.
- **Published** (planned): a daily performance extract and a graph snapshot per agent, a team
  assessment per team, all under the host's prefix; BigQuery external tables for cross-host queries
  such as "which agents complete survey tasks with the fewest failed actions this month".

Goal maturity over time is read from the same data: targets in `metrics.yaml` are revised by
retrospectives, and the assessment keeps the target history beside the measured values.

## 7. Bootstrapping a new host

```mermaid
flowchart TD
    A["Base OS installed and networked<br/>(Ubuntu 22.04/24.04, or Windows 11 + WSL2)"] --> B["bootstrap-host.sh<br/>packages, Docker, Node 22, Python 3.12, zstd, binutils, lsof"]
    B --> C["clone the repository, create .venv, pip install -e .[local]"]
    C --> D["person enters keys by name into the keyring<br/>HG_KEY_<NAME>, ANTHROPIC_API_KEY, host service account"]
    D --> E["hglab local backup pull: latest host backup and graph snapshot from GCS"]
    E --> F["NemoClaw unattended install: provider by hardware<br/>(install-ollama CPU, GPU model, or hosted)"]
    F --> G["hglab local stack --up, hglab local up"]
    G --> H["hglab local cards --publish: the host and its agents appear in the index"]
    H --> I["hglab local service install: survives reboots"]
    I --> J["cut-over check: Pulse not worse for 7 days, then HG_AGENT_<NAME> off on Actions"]
```

The hardware inventory (CPU, RAM, GPU and VRAM, disk, OS) decides step F only; everything else is
identical on every host. See [local-runtime-setup.md](local-runtime-setup.md) for the inventory table
and the model sizing.
