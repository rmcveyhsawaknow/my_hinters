---
name: hg-notebook
description: Store durable private notes within the notebook's 50-key limit and reserved names.
---
# Use the notebook
1. Keep the 50-key maximum in mind; update existing notes and forget stale ones.
2. Reserve `_lease`, `_limits`, `plan`, `places`, `allies`, `debts`, `promises`, `experiments`, and `handoff`.
3. Never copy notebook content to prompts, artifacts, logs, or git; redact before persistence.
4. Keys ≤64 characters and values ≤2000 characters.
Check: notebook does not reach a shared run record or public message.
Example: record a promise's public event ID and due tick under `promises`.
