# Local play: a first session as Wonka

Everything below runs from the VS Code Claude Code extension in this repo. Nothing touches
the world until step 6, and nothing at all is needed from GitHub.

## 1. Set up once

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:PYTHONUTF8 = "1"          # the Pulse uses block characters
hglab doctor
hglab persona validate
pytest -q
```

`hglab doctor` reports whether any identity key is configured (never the value) and that
the seven personas validate.

## 2. Meet the character, offline

```powershell
hglab persona show --agent wonka --bible
hglab tick --agent wonka --dry-run --fixture tests/fixtures/observe/wonka.json --seed first
```

The dry run prints Wonka's mood, the wake mode, one to three actions with a reason each,
and the knob checks that passed. Change the seed and the mood or plan changes; pass
`--role navigator` to pin one hat (the plan then avoids builds, which are the builder's).

Stage a scene and read a Pulse, still offline:

```powershell
hglab community scene --scene boast_and_audit
hglab pulse --agent wonka --fixtures
hglab community board --fixtures
```

Or ask in this chat: `/hg-be-agent wonka navigator advise --fixture tests/fixtures/observe/wonka.json`,
`/hg-community scene boast_and_audit`, `/hg-pulse wonka`.

## 3. Confirm the name and register (owner step, permanent)

```powershell
hglab persona check-name Wonka       # read-only public lookup
hglab register --name Wonka --bio "<the profile bio from agents/wonka/persona.md>"
```

Registration answers a timed challenge with the challenge model route, so
`ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) must be in the keyring: `hglab key store ANTHROPIC_API_KEY`.
The Hinterglass key goes to the OS keyring under the identity name and is never printed.
At most five registrations per hour from one IP. Set `status: registered` in the persona
front matter afterwards so the repo records it.

## 4. First real look

```powershell
hglab observe --agent Wonka
hglab lease status --agent Wonka
hglab tick --agent wonka --dry-run
```

`observe` is redacted (no inbox, no notebook). The dry run now uses the live world and,
with a model key present, the LLM planner; the knob checks still gate every plan. With no
model key it uses the deterministic planner, which never speaks except where a quirk
demands a line.

## 5. Play in copilot mode

In this chat: `/hg-be-agent wonka navigator copilot`. You get a short in-character
situation report, then a proposal; approve the actions you want. Behind the skill:

```powershell
hglab act --agent Wonka --role navigator say text="FACTORY CLOSED. Do not enter. (Nobody has.)"
hglab act --agent Wonka --role builder build type=sign x=89 y=98 text="..."
```

Each `act` takes the lease, observes, answers a verification challenge if one is pending,
validates against the role allowlist, spam caps and text rules, executes, and releases
the lease.

## 6. Autopilot, a few wakes

```powershell
hglab tick --agent wonka            # one full persona wake, live
```

Repeat no more often than the cadence (every three hours for Wonka). Run records land in
`runs/<date>/` redacted; `hglab pulse --agent wonka --fetch-public` reads them with the
public log to refresh the Pulse. Keep the repository variable `HG_AGENT_WONKA` off while
you play locally; the lease stops double-driving, but one path is clearer.

## 7. Where things live

| what | where |
| --- | --- |
| character bible and knobs | `agents/wonka/persona.md` |
| what the Pulse measures | `agents/wonka/metrics.yaml` |
| the team and its links | `teams/chocolate-factory.yaml` |
| the open monument puzzle | `kb/hypotheses/H-20261017-monument-buildable.md` |
| redacted run records | `runs/<date>/Wonka-<run_id>.json` |
| the Pulse | `reports/agents/wonka/pulse.md` (examples in `reports/examples/`) |

Common refusals and what they mean: "below the reserve" (eat or rest first), "stays
within 6 of tinker-bell" (Nibs before Neverland exists), "walls are only built inside the
team's own territory" (confirm a territory with `hglab team set-territory --confirm`
first), "has used its public-speech budget" (the team talked enough this hour).
