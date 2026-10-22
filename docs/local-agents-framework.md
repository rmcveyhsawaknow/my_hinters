# A local agents framework for the collective

Status: decision record and build plan, 2026-10-22. The owner asked for a portable agent-to-agent
protocol and orchestration runtime that runs the same agents on local hardware (Windows or
Linux), keeps a shared memory in a graph store with a keystore for the agents' secrets, shows
status and configuration in a quick UI, is manageable from a CLI and from MCP (Claude Code in
VS Code), snapshots and persists memory for resilience, lets a person move between machines,
and gives an organisation one way to audit and measure agents. The first agent to move from
GitHub Actions to the local runtime is Clarion; the teams follow one by one.

## 1. What the reports say about coordination

Measured on the reports branch for the two days to 2026-10-22 (2,261 wake records):

| finding | evidence |
|---|---|
| Agents act alone. | "goals for peers" is 0 for every agent in `reports/community.md`; no claim on a peer's goal completed. |
| Talk is one-way and repetitive. | 28 whispers from Fudgewright to Stoutheart in two days; whispers never answered in kind. |
| Memory did not survive a wake. | Every live persona state carried no flags: the serializer emptied them once the note passed 2000 characters (fixed in PR #64). |
| Whispers were lost in delivery. | The world marks a whisper read on delivery; the hourly keepalive read the land office's survey answer and the wake never saw it (fixed in PR #62). |
| Notebook state broke silently. | State notes cut at 2000 characters stopped parsing and were forgotten every hour (fixed in PR #61). |
| Orchestration is slow and blind. | A wake is a GitHub Actions job: checkout, install, observe, act, publish; 2,351 runs and about 378 wall-clock hours in five days; one agent cannot see another's plan until the reports branch publishes. |
| Measurement is loose. | `reports/community.md` shows every approach with 0 wakes: the planner's approach labels and the metrics specs drifted apart. |

Conclusion: the collective lacks three things a runtime should provide, a shared memory the
agents read before planning, a message path that does not depend on the world's inbox, and a
scheduler that runs wakes in seconds rather than minutes. The world (Hinterglass) stays the only
place actions happen; coordination moves off-world.

## 2. The research, in short

**NemoClaw (NVIDIA).** An open-source stack that runs OpenClaw inside NVIDIA's OpenShell sandbox
with managed inference. Prerequisites on the current docs: Linux is the primary tested path,
Windows via WSL2 is "tested with limitations" with the Docker Desktop backend or rootless Podman;
4 vCPU and 8 GB RAM minimum (16 GB recommended), 20 to 40 GB disk, Node 22.19+, npm 10+, a
container runtime, `binutils`. The installer is `curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`,
a thin bootstrap that clones a pinned ref of `github.com/NVIDIA/NemoClaw` and runs its installer;
unattended installs use `NEMOCLAW_NON_INTERACTIVE=1`, `NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1`,
`NEMOCLAW_AGENT=openclaw`, `NEMOCLAW_PROVIDER` (`openrouter | openai | anthropic | anthropicCompatible | build`),
`NEMOCLAW_SANDBOX_NAME`, `NEMOCLAW_POLICY_MODE`. Inference providers include NVIDIA endpoints
(Nemotron), OpenRouter, OpenAI, Anthropic, Gemini, OpenAI- and Anthropic-compatible endpoints,
local Ollama and vLLM, so no GPU is needed when a hosted key is used. The sandbox applies a
network policy tier (Balanced, Restricted, Open) and the dashboard is forwarded to
`http://127.0.0.1:18789/` with a gateway token. Sources: the NVIDIA prerequisites and quickstart
pages (docs.nvidia.com/nemoclaw/latest), the Spheron and Second Talent install guides.

**OpenClaw.** The agent host inside NemoClaw: a gateway daemon (WebSocket on 18789) with a Control
UI, CLI (`openclaw onboard`, `openclaw gateway install`, `openclaw dashboard`, `openclaw agents add`),
plain-file workspaces (`AGENTS.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, `memory/YYYY-MM-DD.md`),
skills as folders with `SKILL.md` (the same convention this repo uses), a heartbeat and a cron
scheduler ("Automations": one-shot, interval and cron schedules, isolated runs, delivery to a
channel or webhook), hooks and authenticated webhooks. Multi-agent: `agents.entries.<id>` with its
own workspace, agent dir and session store; routing by `bindings`; agent-to-agent through
`sessions_send`, `sessions_history`, `sessions_list`, `sessions_spawn` governed by
`tools.agentToAgent`; sub-agents through `agents.entries.<id>.subagents.allowAgents`. Config lives
in `~/.openclaw/openclaw.json`. Sources: docs.openclaw.ai (`/concepts/multi-agent`, `/automation`,
`/cli`, `/gateway`, `/web/control-ui`).

**A2A (Agent2Agent).** Linux Foundation protocol, specification 1.0.0: an Agent Card for discovery,
tasks with states `SUBMITTED`, `WORKING`, `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`,
`CANCELED`, `REJECTED`, operations Send Message, Send Streaming Message, Get Task, Cancel Task and
push-notification configs, bindings for JSON-RPC, gRPC and HTTP+JSON, security schemes from API
key to mutual TLS. Python SDK `a2a-sdk` 1.2.3 on PyPI. Source: a2a-protocol.org/latest/specification.

**MCP.** The management surface Claude Code already speaks. Python SDK `mcp` 2.3.0 (and `fastmcp`
4.1.3) on PyPI.

**Graph store.** Kùzu was archived after Apple bought the company in October 2025; LadybugDB is
the MIT-licensed fork with the same Python API (`pip install ladybug`, 0.21.2). On this Windows
machine the wheel installs but needs a separately downloaded native library (`lbug_shared.dll`),
so it is not portable out of the box. The framework therefore ships its own small property graph
on SQLite (nodes, edges, JSON properties, snapshots), portable everywhere Python runs, with the
store behind an interface so LadybugDB (Cypher) can replace it on Linux hosts later.

**Keystore.** The agents' Hinterglass keys already live in the OS keyring (Windows Credential
Manager here; Secret Service on Linux) and in GitHub secrets for Actions. NemoClaw keeps provider
credentials inside the sandbox. For an organisation, the same interface can point at OpenBao or
HashiCorp Vault; nothing in the repo holds a key.

**This machine.** Windows 11 Pro, Ryzen 9 5900HX (8 cores, 16 threads), 31 GB RAM, Radeon
integrated graphics (no NVIDIA GPU), 66 GB free on C:, WSL2 Ubuntu 22.04 with Docker Desktop
29.2 integrated from today, Node 24 on Windows and Node 22 in WSL from today, Python 3.12.

## 3. The decision

A hybrid: the world is the only place actions happen; coordination, memory and scheduling move
onto the local host; NemoClaw hosts the operator's conversational agent and sandboxes anything that
talks to the outside; the deterministic persona runtime stays in this repo as `hglab` and gains
local endpoints.

```
  Claude Code (VS Code)  ──MCP──▶  hglab mcp  ──────────────┐
  OpenClaw (NemoClaw sandbox, operator agent "Warden")      │   hglab local supervisor
      │  cron / heartbeat / chat                            ├─▶ (scheduler, leases, snapshots)
      └──A2A over http://127.0.0.1:8765 ──▶ hglab a2a ──────┘          │
                                                                       ▼
   hglab ui  (http://127.0.0.1:8766, status + config)     memory graph (SQLite, snapshots)
                                                                       │
                                                          Hinterglass REST (the world)
```

- **Runtime** (`hglab local`): one process per host runs the persona wakes, work shifts, keepalives
  and office rounds on the personas' own cadence knobs, in seconds, with the world's notebook lease
  still preventing two runtimes from acting as one agent. It writes a status file and the memory
  graph, and publishes redacted records to the reports branch the same way Actions does. GitHub
  Actions stays as the fallback runtime for any agent not yet migrated.
- **Protocol**: A2A 1.0 between agents and operators (one Agent Card per persona at
  `/.well-known/agent-card.json` under its own path, Send Message mapped to an in-world whisper
  or a goal proposal, Get Task for its state); MCP for management (list agents and teams, status,
  run a dry wake, pause or resume, query memory, snapshot and restore, read a Pulse).
- **Memory**: a property graph of agents, teams, goals, promises, interactions (whispers, gives,
  deeds, surveys), structures and snapshots, fed from the records and the public log, read by the
  planner before a wake (who promised what, who is where, what is in flight). Snapshots are
  dated copies of the store; moving machines means copying the store and the keyring entries.
- **Security**: the OS keyring for identity keys and model keys; the NemoClaw sandbox and its
  network policy for the operator agent; nothing private in the graph beyond what the notebook
  already holds, and whispers are kept only as the agents' own notes.
- **Measurement**: the Pulse and the reports branch stay the organisation's common view; the graph
  adds queryable history (promises kept, replies answered, goals completed for peers) that an
  auditor can export.

## 4. The plan

1. **Foundations in this repo** (`src/hglab/local/`): the graph store and snapshots, the supervisor,
   the MCP server, the A2A server, the status UI, `config/local.yaml` with its schema, tests, and
   `hglab local` commands. No change to how Actions runs today.
2. **NemoClaw on this machine** (WSL2 Ubuntu): prerequisites are in place; install with the
   unattended flags, provider Anthropic (the collective's existing route), policy Balanced plus an
   endpoint preset for the local hglab ports; confirm the dashboard; add the `hglab` MCP server and
   A2A cards to the operator agent.
3. **Clarion first**: run the local supervisor for Clarion live while his Actions schedule still
   runs (the lease makes the two take turns), watch for a day, then switch his Actions variable off
   and keep the local runtime as the only one. Then The Square's duties (feature watch, collector
   round), then LandBroker, the Chocolate Factory and Neverland, team by team.
4. **Coordination features the local runtime enables**: a team plan read before each wake, promises
   as graph edges with due ticks, a reply obligation (an unanswered whisper is a next-wake action),
   peer goals as tasks on the A2A board.

## 5. Running it

Everything below is keyless and dry unless `--live` is given; the world's notebook lease still keeps
one runtime per agent, so a local live run and an Actions run of the same persona take turns.

```text
hglab local status [--json]                      # who runs locally, last job, what is due
hglab local once --agent town-crier --job tick   # one job now (tick, shift, keepalive, crier, land)
hglab local run [--minutes N]                    # the supervisor loop on the personas' cron knobs
hglab local ui [--port 8766 --open]              # the status page and /status.json
hglab local a2a [--port 8765 --token T]          # Agent Cards and the message endpoint
hglab local mcp                                  # the management server over stdio
hglab local memory ingest [--no-events]          # records and the public log into the graph
hglab local memory query "select ..." | contacts NAME | snapshot [NAME] | restore NAME
```

`config/local.yaml` lists which personas the local runtime owns and whether each is dry; the
schema is `schemas/local.json` and `hglab config validate` checks it. State lives under `runs/local/`
(ignored by git): `status.json`, `supervisor.log`, `memory.sqlite` and `memory.snapshots/`.

**Claude Code**: `.mcp.json` registers the server as `hinters` (`hglab local mcp`), so a session
opened in this repository with the virtual environment on its PATH can call `agents`, `teams`,
`status`, `run_job`, `memory_query`, `contacts`, `promises`, `snapshot` and `agent_cards`. Another
client adds it with `claude mcp add hinters -- hglab local mcp`.

**OpenClaw / NemoClaw**: the operator agent reaches the same server through its `mcp.servers`
block (stdio, command `hglab`, args `local mcp`) and the personas through the A2A cards at
`http://127.0.0.1:8765/agents`; the sandbox policy needs an endpoint entry for 127.0.0.1 ports
8765 and 8766.

## 6. Sources

- NemoClaw prerequisites: https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/prerequisites
- NemoClaw quickstart: https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart
- NemoClaw install guides: https://www.spheron.network/blog/deploy-nvidia-nemoclaw-gpu-cloud-ai-agents/ and https://www.secondtalent.com/resources/how-to-install-nvidia-nemoclaw/
- OpenClaw docs: https://docs.openclaw.ai/ (multi-agent: /concepts/multi-agent, automation: /automation)
- OpenClaw architecture write-ups: https://www.betterclaw.io/blog/how-does-openclaw-work and https://www.stack-junkie.com/blog/openclaw-workspace-architecture
- A2A specification 1.0: https://a2a-protocol.org/latest/specification/ and https://atlan.com/know/mcp/a2a-protocol-implementation-guide/
- Kùzu archived, LadybugDB fork: https://github.com/LadybugDB/ladybug and https://www.helix-db.com/content/alternatives/kuzu-alternatives-in-2026-embedded-graph-databases

## 7. NemoClaw on this machine: status on 2026-10-22

Installed keyless and unattended in WSL2 Ubuntu (Docker Desktop with WSL integration, Node 22.19 from
a user-local tarball, zstd unpacked from the Ubuntu package into the home directory because sudo has
no password in the shell that runs installs):

```text
NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_AGENT=openclaw
NEMOCLAW_PROVIDER=install-ollama NEMOCLAW_MODEL=qwen3.5:9b NEMOCLAW_OLLAMA_INSTALL_MODE=user
NEMOCLAW_SANDBOX_GPU=0 NEMOCLAW_SANDBOX_NAME=hinters NEMOCLAW_POLICY_MODE=suggested
```

Result: NemoClaw v0.0.137, OpenShell 0.0.116 gateway as a user service, Ollama in user-local mode
serving qwen3.5:9b on 127.0.0.1:11434 behind the token proxy on 11435, sandbox `hinters` Ready with
OpenClaw v2026.9.2 running, policies npm, pypi, huggingface, brew-balanced and openclaw-pricing.
`NEMOCLAW_DEFER_ONBOARDING` is refused for the OpenClaw agent, so onboarding had to run.

Onboarding stops at the policies step. The in-sandbox inference proof posts to
`http://host.openshell.internal:11435/v1/chat/completions`; the L7 rule allows it and the SSRF
guard then denies it, because the alias resolves to an IPv6 unique-local address
(`fdc4:f303:9324::254`, beside `192.168.65.254`) and the generated provider policy pins only
`10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`. The pins come from
`src/lib/inference/native-local/profile.ts` in NemoClaw (installed copy under
`~/.nemoclaw/source/dist/lib/inference/native-local/profile.js`). Two ways forward, both the
owner's decision: add `fc00::/7` to that list and run `nemoclaw onboard --resume --non-interactive`,
or report it upstream and wait. The session did not change the policy.

After onboarding completes: `nemoclaw hinters dashboard-url` for the OpenClaw UI, then an
`mcp.servers` entry for `hglab local mcp` and a policy endpoint for 127.0.0.1 ports 8765 and 8766 so
the operator agent can reach the collective's cards and status page.

Clarion locally: a dry `hglab local once --agent town-crier --job tick` observes the live world (the
key resolves locally), so the first live confirmation is
`hglab local once --agent town-crier --job tick --live`, run by the owner; the lease makes the local
run and the Actions run take turns.
