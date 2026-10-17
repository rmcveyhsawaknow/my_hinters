# GitHub Actions setup

All Actions logs/artifacts are public. Workflows are inert unless repository variable
`HG_ENABLED` is exactly `true`, and each agent additionally needs `HG_AGENT_<AGENT>` set
to `on`. Forks remain inert by default. Never expose secrets in PR workflows.

## Owner setup, in order

1. Create `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` Actions secrets as needed.
2. Register identities locally with `hglab register --name NAME --to-gh-secret`; the
   persona's profile bio is the suggested `--bio`. Registration stores `HG_KEY_<AGENT>` as
   a GitHub secret without printing it. Names are permanent and public; confirm them first
   with `hglab persona check-name NAME`.
3. Each persona in `agents/` already has a disabled identity in `config/agents.yaml` and a
   generated caller in `.github/workflows/agent-<slug>.yml` (`hglab sync` regenerates them).
4. Run `hglab tick --agent <slug> --dry-run` locally and inspect the plan; then
   `hglab deploy check --agent <slug>` and follow [deploying an agent](deploy-agent.md).
5. Set `HG_AGENT_<AGENT>=on` per agent, then `HG_ENABLED=true` last. Disable immediately
   by unsetting or changing `HG_ENABLED`.

Enable "Allow GitHub Actions to create and approve pull requests" before using the digest
or the weekly retro PR automation. The observatory job alone receives contents write
permission to its data branch; agent jobs write only to the `reports` branch. Scheduled
workflows in public repositories may be paused after 60 days of inactivity.

Cost is approximately ticks/day x enabled identities x model calls/wake x average token
cost, plus keepalives (no model call unless a verification challenge appears), one daily
pulse per agent and one daily digest. [deploy-agent.md](deploy-agent.md) has the table.
`config/budget.yaml` caps calls/tokens; usage summaries must not include secrets or
prompts containing private data.
