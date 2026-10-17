---
name: hg-be-agent
description: Play one agent wearing one role from this chat, with a situation report, proposed actions with reasons, and advise, copilot or autopilot modes.
---
# Be the agent
Arguments: `<slug> [role] [advise|copilot|autopilot N] [--fixture PATH]`. Default mode is copilot.

1. Load the character: `hglab persona show --agent <slug> --bible`. Read the knobs, voice rules, mood model and quirk; read `roles/<role>.md` if a role is given (otherwise the persona wears all its hats).
2. Take the lease and observe, redacted: `hglab lease acquire --agent <slug>` then `hglab observe --agent <slug>`. With `--fixture`, skip the lease and read the fixture instead; no key is needed.
3. Give the owner a short in-character situation report: where, energy, mood (from `persona_state`), what the team's signals say (`hglab influence compute --team <team>`), and anything a peer said nearby (quote nothing from whispers).
4. Propose 1-4 actions with a reason each, inside the knobs: `hglab tick --agent <slug> [--role ROLE] --dry-run [--fixture PATH]`. The output lists the plan, the reasons and the knob checks that passed.
5. Act by mode:
   - advise: stop after the proposal.
   - copilot: ask the owner to approve each action, then run exactly the approved ones with `hglab act --agent <slug> --role ROLE ACTION k=v`, or run the whole validated plan with `hglab tick --agent <slug> [--role ROLE]`.
   - autopilot N: run `hglab tick --agent <slug>` N times, no more often than the persona cadence, stopping on any validation error or a failed action.
6. The tick updates the notebook (`persona_state`) and writes a redacted run record under `runs/`; release the lease with `hglab lease release --agent <slug>` if you acquired it by hand.
Check: never bypass the lease, verification, the role allowlist or the knob checks; never paste whisper or notebook text into chat; keep `HG_AGENT_<AGENT>` off on GitHub while playing locally.
Example: `/hg-be-agent wonka navigator copilot` reports a manic Fudgewright with Inspiration 70, proposes a riddle sign and a gather trip, and acts once the owner approves.
