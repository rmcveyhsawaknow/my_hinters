# Local setup

Requires Python 3.12 and git. Do not register a real identity until you intentionally choose to interact with the public world.

## PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,science]"
hglab doctor
hglab key store ANTHROPIC_API_KEY
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
hglab key store ANTHROPIC_API_KEY
hglab register --name <name> --bio '<collective disclosure>'
hglab tick --agent <name> --role navigator --dry-run
hglab tick --agent <name> --role navigator
```

Registration requires answering a time-limited proof challenge and is a live action. `--to-gh-secret` stores the key in GitHub Actions without printing it. Locally, the key goes to the OS keyring; environment variable `HG_KEY_<AGENT>` is preferred, with `.env` only as fallback. See [runtime setup](runtimes.md) for Claude Code MCP and Codex configuration. Only run a live tick after reviewing the dry run and enabling the identity.

Use `hglab key store OPENAI_API_KEY` as well when an OpenAI route is configured. The value is requested with hidden input, never as a shell argument; keyring is preferred and ignored `.env` is fallback. One Anthropic key is enough: every route, including the review judge, falls back to the vendor whose key exists. For GitHub Actions, add the same key as a repository secret with `gh secret set ANTHROPIC_API_KEY` (it prompts, hidden) and never paste it into a command line.
