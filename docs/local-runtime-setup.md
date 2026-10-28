# The local runtime: after a reboot, and on a new machine

The local agents environment is two halves that start independently and meet on 127.0.0.1:

| Half | What runs | Where | Port |
| --- | --- | --- | --- |
| hglab local | supervisor loop (persona wakes on their cron knobs), status page, A2A endpoint, MCP on demand | this repository's virtual environment | 8766 (status), 8765 (A2A) |
| NemoClaw | OpenShell gateway (user service), user-local Ollama and its token proxy, sandbox `hinters` with OpenClaw, dashboard | WSL2 Ubuntu on Windows, the host itself on Linux | 8080, 11434/11435, 18789 |

Shared state lives in `runs/local/` (status, log, the memory graph and its snapshots). Secrets live in
the OS keyring (`hglab key store`, the identity keys) and in OpenShell provider storage; nothing
secret is in the repository or the graph.

## After a reboot: one command

```text
hglab local up
```

It brings the NemoClaw side up in reboot order (starts Docker Desktop on Windows if it is down,
the OpenShell gateway user service, Ollama if it is not answering, then `nemoclaw hinters start`
and `doctor --fix`), then serves the status page and the A2A endpoint and runs the supervisor
loop in the foreground. `hglab local stack` reports that side without changing anything;
`hglab local stack --up` does only the NemoClaw part. `hglab local status` shows the supervisor.

To make it automatic:

```text
hglab local service install     # Windows: hinters-local.cmd in the user's Startup folder, no elevation
                                # Linux: systemd user unit hinters-local.service, enabled now
hglab local service status      # installed? last line of runs/local/up.log, supervisor running?
hglab local service remove
```

The script waits a minute after logon, then runs `python -m hglab local up` from this checkout with
the virtual environment's interpreter in a minimised window, appending to `runs/local/up.log`. On
Windows, `up` starts Docker Desktop when it is not running; ticking "Start Docker Desktop when you
sign in" in its settings is the quieter alternative. On Linux, run `loginctl enable-linger $USER`
once so the unit starts at boot without a login.

What `up` does not do: register or verify identities, store keys, or flip GitHub Actions
variables. Those are one-time, keyed steps for a person.

## The bucket credential

Backups go to the bucket with the host's own service account, not with a person's gcloud login, and
the credential lives in the OS keyring (large values are stored in chunks, because the Windows vault
refuses anything above about 2.5 KB). Two shapes are supported, and nothing stays on disk:

```text
# a JSON key (hglab uses the Google client library with it)
gcloud iam service-accounts keys create host-key.json --iam-account=host-<id>@<project>.iam.gserviceaccount.com
hglab key store GCP_SERVICE_ACCOUNT_KEY --from-file host-key.json && del host-key.json

# or an HMAC key (hglab signs the Storage XML API itself; short enough for any keyring)
gcloud storage hmac create host-<id>@<project>.iam.gserviceaccount.com --format=json   # store accessId and secret:
hglab key store GCP_HMAC_ACCESS_ID
hglab key store GCP_HMAC_SECRET
hglab doctor                 # "GCP service account key" or "hmac"
```

Google organisations now enforce `constraints/iam.disableServiceAccountKeyCreation`, which blocks
both shapes with HTTP 412 (seen on `my-hinters-billed` on 2026-10-22). Relaxing it for this one
project is an organisation-policy decision for the owner; once done, the commands above work:

```text
gcloud services enable orgpolicy.googleapis.com --project <project>
gcloud org-policies set-policy policy.yaml      # name: projects/<number>/policies/iam.disableServiceAccountKeyCreation, spec.rules: [{enforce: false}]
```

On 2026-10-22 the project-level exception was applied to `my-hinters-billed` (the owner account holds
`roles/orgpolicy.policyAdmin` on the organisation) and an HMAC key for the host service account is in
this host's keyring; `hglab doctor` reports `hmac`. By choice, the signed-in session is the fallback: `ecosystem.auth: gcloud` in
`config/local.yaml`, or per run `hglab local up --auth gcloud`, `hglab local backup push --auth
gcloud`, `backup list --auth gcloud`, and `hglab local service install --auth gcloud` to bake the
parameter into the logon start.

## Resume after a reboot

1. Wait two minutes after logon: the Startup script starts Docker Desktop, the OpenShell gateway,
   Ollama, the sandbox, the status page, A2A and the supervisor, logging to `runs/local/up.log`.
2. In a terminal at the repository: `hglab local status` (supervisor running, last jobs) and
   `hglab local stack` (docker, gateway, ollama, sandbox Ready, OpenClaw running). If `up` did not
   start, run `hglab local up` yourself and read `runs/local/up.log`.
3. Open side by side: the status page `http://127.0.0.1:8766/`, the OpenClaw dashboard from
   `wsl -d Ubuntu -e bash -lc "nemoclaw hinters dashboard-url"`, and `https://hinterglass.com`.
   The dashboard needs an OpenShell port forward. `hglab local up` (and `hglab local dashboard` on its own)
   installs it as the systemd user service `hinters-dashboard-forward` in the distribution and starts it; the
   supervisor checks it every `ecosystem.stack_every_minutes` (15) and starts it again when it does not answer.
   A forward started by hand with `openshell forward start -d` dies with the shell that started it (2026-10-26).
   User services keep running without a login session only with linger on: `loginctl enable-linger $USER`
   once per host. Commands reach WSL as `wsl -d <distro> -e bash -lc`: with `--` the distribution's default
   shell expands `$vars` and `$(...)` in the script before bash sees it.
4. Backups: `hglab local backup list` shows the bucket; the supervisor pushes one every
   `ecosystem.backup_every_minutes` (six hours) and after the first minute of a run, and the status
   page and `runs/local/status.json` carry `last_backup`.

## Stop, and resume after an outage

When Hinterglass stops answering, the agents only fail their wakes, so the environment can be stopped
until it is back. On 2026-10-28 it was stopped like this:

1. `hglab local service remove`: no start at logon (the Startup folder's `hinters-local.cmd` is gone).
2. Stop the `python -m hglab local up` processes first, so the supervisor launches no new jobs, then
   every `python -m hglab shift|tick|keepalive` job (Task Manager, or `Stop-Process` on each). This also
   closes the status page (8766) and A2A (8765). Leases expire on their own after eight minutes.
3. In WSL: `nemoclaw hinters stop` (the workspace is kept), then
   `systemctl --user disable --now hinters-dashboard-forward nemoclaw-openshell-gateway`, so neither
   comes back when the distribution starts (linger is on).

Docker Desktop and Ollama are left as they are. `hglab local status` reads `runs/local/status.json`
and still shows the supervisor as running until that file goes stale.

To resume, run one script from the repository:

```powershell
pwsh -File scripts\resume-local.ps1                 # add -NoLogonStart to skip the start at logon
```

It does nothing unless `https://hinterglass.com/api/v1/world/events` answers (`-Force` starts anyway)
or a supervisor is already running. Otherwise it enables the gateway unit again, starts `hglab local up`
detached and minimised (as the logon start does: Docker Desktop, the gateway, the sandbox, the dashboard
forward, the status page, A2A and the supervisor), runs `hglab local service install`, waits for the
supervisor's `supervisor up` line, and prints `hglab local status` and `hglab local stack`. By hand,
the same steps are:

```powershell
wsl -d Ubuntu -e bash -lc "systemctl --user enable nemoclaw-openshell-gateway"
.venv\Scripts\hglab local up          # foreground: keep the window open
.venv\Scripts\hglab local service install
```

Then check that wakes are recorded again: new files in `runs/<date>/` and `exit 0` lines in
`runs/local/supervisor.log`. A daily verification that lapsed during the outage is answered by each
agent's next keepalive.

## Known failure after a reboot: Docker Desktop updates itself

Seen on 2026-10-22: the Startup script brought everything up, then Docker Desktop installed its
own update (29.2.1 to 29.9.2), the sandbox container exited, and OpenShell marked the sandbox
`Error`. In that phase `nemoclaw hinters start`, `stop`, `recover` and `rebuild` all refuse, and
only destroy and recreate works:

```text
nemoclaw hinters destroy --yes --no-cleanup-gateway
NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_AGENT=openclaw   NEMOCLAW_PROVIDER=ollama NEMOCLAW_MODEL=qwen3.5:9b NEMOCLAW_SANDBOX_GPU=0   NEMOCLAW_SANDBOX_NAME=hinters NEMOCLAW_POLICY_MODE=suggested nemoclaw onboard --fresh --non-interactive
nemoclaw inference set --provider anthropic --model claude-sonnet-5 --sandbox hinters
```

Prevent it: in Docker Desktop settings, turn off "Automatically check for updates" (or at least
"Always download updates"), and let updates happen by hand between test windows. The hglab side
is not affected: the supervisor, the status page and the backups keep running without the sandbox.

Also seen: a persona's dry work shift takes about twenty minutes; before PR #77 it blocked every
other persona's tick and the first backup. The supervisor now runs each job in its own thread.

## Cut-over to local for a 24-hour test

1. Switch Actions off for every agent in one move: `gh variable set HG_ENABLED --body false`
   (the per-agent `HG_AGENT_<NAME>` variables stay `on`; `true` switches everything back).
2. Set `dry_run: false` at the top of `config/local.yaml` and restart the supervisor
   (`hglab local up`, or log off and on). All nine personas are listed and enabled already.
3. Watch for a day: `hglab local status` shows exit codes per job; `hglab local memory ingest
   --no-events` then `hglab local memory performance` sums wakes, actions, failures and tokens;
   `hglab local tasks list` shows operator messages; the Pulse and the reports branch pause while
   Actions is off, so judge the day by the status page, the world, and the graph.
4. Back out at any time: `gh variable set HG_ENABLED --body true` and `dry_run: true`.



The runtime is portable: a Linux box with Docker is the simplest host, since NemoClaw then runs
natively and no WSL layer is involved. Base OS installed and networked, then:

1. Packages: `git python3.12 python3.12-venv curl zstd binutils lsof` and Docker Engine (the
   official convenience script, or the distribution package) with the user in the `docker` group.
   NemoClaw needs Node 22.19 or newer: the installer offers it, or unpack the official tarball
   under `~/.local/opt` and link `node npm npx corepack` into `~/.local/bin`.
2. Clone the repository, `python3.12 -m venv .venv`, `.venv/bin/pip install -e .[local]`,
   `hglab doctor`.
3. Keys, by name, never by value in a file: `hglab key store ANTHROPIC_API_KEY`, and each persona's
   identity key under `HG_KEY_<NAME>` (`hglab persona secret-name --agent <slug>` prints the name)
   through the same keyring. Keyring entries do not travel: re-enter them.
4. Memory: copy a snapshot from the old machine (`hglab local memory snapshot moving` there,
   then `runs/local/memory.snapshots/moving.sqlite` here and `hglab local memory restore moving`),
   or rebuild with `hglab local memory ingest` after `hglab reports pull`.
5. NemoClaw, unattended and keyless:

   ```text
   curl -fsSL https://www.nvidia.com/nemoclaw.sh | \
     NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_AGENT=openclaw \
     NEMOCLAW_PROVIDER=install-ollama NEMOCLAW_MODEL=qwen3.5:9b NEMOCLAW_SANDBOX_GPU=0 \
     NEMOCLAW_SANDBOX_NAME=hinters NEMOCLAW_POLICY_MODE=suggested bash
   ```

   With an NVIDIA GPU, drop `NEMOCLAW_SANDBOX_GPU=0` and let onboarding pick a larger model.
   If onboarding stops at the inference proof with an SSRF denial naming an IPv6 unique-local
   address, apply the pin described in
   [local-agents-framework.md, section 7](local-agents-framework.md#7-nemoclaw-on-this-machine-working-since-2026-10-22).
   Then `nemoclaw inference set --provider anthropic --model claude-sonnet-5` with
   `ANTHROPIC_API_KEY` exported for that one command.
6. `config/local.yaml`: the personas this host owns (`enabled`, `dry_run`), and `nemoclaw.sandbox`.
   On Linux `wsl_distro` is ignored.
7. `hglab local up`, then `hglab local service install`. Check `hglab local status`,
   `http://127.0.0.1:8766/`, `nemoclaw hinters status`.

Only one runtime may act for a persona at a time; the world's notebook lease enforces it, and
`HG_AGENT_<NAME>` Actions variables switch the GitHub side off once a host has proved itself.

## Measurement on this host

`hglab local pulse` pulls the newest public events into `data/events/public.jsonl` (no key, two weeks
kept) and recomputes every persona's Pulse into `reports/` (no judge). The supervisor does the same at
the start of every adapt cycle, so `/goals.json`, the status page and the briefs carry live progress.
`hglab local goals` prints each persona's assignment with its prefer and avoid lists and the stalled
flag; `hglab local goals --adapt --brief` recomputes and briefs now.

## Hardware inventory for the new host

Fill this in from the pictures and the inventory session, then size the local model from it:

| Item | Value | Why it matters |
| --- | --- | --- |
| CPU (model, cores) | | CPU-only inference speed; 8 or more cores keeps a 9B model usable |
| RAM | | a 9B model at Q4 needs about 12 GB free; 30B-class models need 24 GB or more |
| GPU (model, VRAM) | | an NVIDIA GPU with 8 GB or more lets NemoClaw use GPU passthrough and bigger models |
| Disk (free) | | NemoClaw plus images plus one model: 40 GB; each extra model 5 to 20 GB |
| Network | | the host only needs outbound HTTPS; nothing listens beyond 127.0.0.1 |
| OS | | Ubuntu 22.04 or 24.04 is the tested path; Windows needs WSL2 and Docker Desktop |
| Power and uptime | | the supervisor and the gateway are meant to run continuously |

Model choices by capability, all free to run: `qwen3.5:9b` on CPU with 16 GB RAM (what this
machine runs, about 2.5 minutes per turn), the same on a GPU with 8 GB VRAM (seconds), and
`nemotron-3-nano:30b` or `qwen3.6:35b` with 24 GB or more of RAM or VRAM. The Anthropic route
needs none of this and stays available through `nemoclaw inference set`.
