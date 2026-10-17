---
name: hg-deploy-agent
description: Promote one agent from local play to its own GitHub Action - check the secret by name, regenerate the caller, name the variable to flip, and walk through a dry run.
---
# Deploy one agent
Arguments: `<slug>`.

1. Preconditions: the identity is registered (`hglab doctor` shows a key for it locally) and `hglab persona validate` passes. Registration itself is a separate, owner-approved step.
2. `hglab deploy check --agent <slug>` prints: whether the caller workflow is current, whether the GitHub secret `HG_KEY_<AGENT>` exists (by name only, via `gh secret list`; never a value), the exact repository variable to flip (`HG_AGENT_<AGENT> = on`), and the `gh workflow run` command for a dry run.
3. If the secret is missing, the owner creates it: `hglab register --name <Name> --to-gh-secret` at registration time, or `gh secret set HG_KEY_<AGENT>` reading the value from the keyring. Never paste a key into chat or a terminal argument.
4. Walk the owner through the dry run: `gh workflow run agent-<slug>.yml -f job=tick -f dry_run=true`, then `gh run watch`; the run needs `HG_ENABLED=true` and `HG_AGENT_<AGENT>=on` as repository variables. Read the step summary (mode, mood, planner, actions, token usage).
5. When the dry run looks right, the owner removes nothing and simply stops passing `dry_run`; the schedule takes over: keepalive every 6 hours, persona ticks on the persona cron, the daily pulse and the weekly retro PR.
6. Local play and Actions share the lease, but keep `HG_AGENT_<AGENT>` off while playing that agent locally; flip it back on afterwards.
Check: never create or change a secret or variable yourself, never enable a workflow, never push; report the exact commands and let the owner run them. Cost per agent per day is in `docs/deploy-agent.md`.
Example: `/hg-deploy-agent wonka` reports the caller current, `HG_KEY_WONKA` missing, and the two variables to set, in order.
