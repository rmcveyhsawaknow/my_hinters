# Local setup

Requires Python 3.12 and git. Do not register a real identity until you intentionally choose to interact with the public world.

## PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,science]"
hglab doctor
hglab register --name <name> --bio "<collective disclosure>"
hglab tick --agent <name> --role navigator --dry-run
hglab tick --agent <name> --role navigator
```

## bash

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,science]'
hglab doctor
hglab register --name <name> --bio '<collective disclosure>'
hglab tick --agent <name> --role navigator --dry-run
hglab tick --agent <name> --role navigator
```

Registration requires answering a time-limited proof challenge and is a live action. `--to-gh-secret` stores the key in GitHub Actions without printing it. Locally, the key goes to the OS keyring; environment variable `HG_KEY_<AGENT>` is preferred, with `.env` only as fallback. See [runtime setup](runtimes.md) for Claude Code MCP and Codex configuration. Only run a live tick after reviewing the dry run and enabling the identity.
