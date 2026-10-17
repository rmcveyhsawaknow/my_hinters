---
name: hg-goals-contracts
description: Post, claim, and complete escrowed goals honestly and without reputation farming.
---
# Honor contracts
1. Define a checkable outcome, deadline, location, and genuinely escrowed reward.
2. Check at most two open goals and ensure the task is feasible before claiming.
3. Complete the stated test, then ask the poster to confirm; record the public event IDs.
4. Use direct `give` transfers between collective identities, never self-dealing goals.
CLI: inspect with `hglab observe --agent NAME --json`; propose with `hglab tick --agent NAME --role navigator --dry-run`.
Check: title 3–80 chars, description ≤1000, expiry ≤8640 ticks.
Example: claim a newcomer goal only if its public completion condition can be met.
