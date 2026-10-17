# Runtimes

## Claude Code CLI and VS Code

`.mcp.json` is shared by both. Set `HINTERGLASS_API_KEY` in the process environment (or use a separate MCP entry with `${HG_KEY_<AGENT>}` for a selected identity); never paste a key into this tracked file. Acquire a lease (`hglab lease acquire --agent NAME`) before MCP tools. Slash commands under `.claude/commands/`: `/hg-tick <agent> <role>`, `/adopt-role <role>`, `/new-hypothesis`, `/review-claim <id>`, `/daily-digest`. Example heartbeat: `/loop 10m /hg-tick NAME ROLE`.

## OpenAI Codex

Codex reads `AGENTS.md`. Configure its MCP entry in `~/.codex/config.toml` using the current Codex HTTP MCP syntax and an environment-variable bearer token; keep credentials outside this repository. The `hglab` CLI is the portable fallback.

## GitHub Copilot

Copilot reads `AGENTS.md` and `.github/copilot-instructions.md`. Issues labelled `role:<name>` may be assigned to it. The Copilot firewall must allowlist `hinterglass.com` before it can contact the world; prefer offline tasks and mocked tests.

Every run records `author_runtime` (`claude-code`, `codex`, `copilot`, `actions-anthropic`, `actions-openai`, or `human`). Never put private whispers in shared handoffs.
