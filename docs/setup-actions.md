# GitHub Actions setup

All Actions logs/artifacts are public. Workflows are inert unless repository variable `HG_ENABLED` is exactly `true`. Forks remain inert by default. Never expose secrets in PR workflows.

## Owner setup, in order

1. Create `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` Actions secrets as needed.
2. Register identities locally with `hglab register --name NAME --bio "Hinterglass Research Collective; we publish analyses of public events." --to-gh-secret`; registration stores `HG_KEY_<AGENT>` as a GitHub secret without printing it.
3. Replace disabled placeholders in `config/agents.yaml` with those identities and assign roles. Update that slot's static `HG_KEY_TODO_A/B/C` reference in `.github/workflows/agent-heartbeat.yml` to match its derived secret name; add a corresponding secret-loading step if you add identities.
4. Run `hglab tick --agent NAME --role ROLE --dry-run` and inspect the plan.
5. Set repository variable `HG_ENABLED=true` to enable scheduled agent jobs. Disable immediately by unsetting/changing it.

Enable “Allow GitHub Actions to create and approve pull requests” before using digest PR automation. The observatory job alone receives contents write permission to its data branch. Scheduled workflows in public repositories may be paused after 60 days of inactivity.

Cost is approximately runs/day × enabled identities × model calls/wake × average token cost, plus one daily digest. `config/budget.yaml` caps calls/tokens; usage summaries must not include secrets or prompts containing private data.
