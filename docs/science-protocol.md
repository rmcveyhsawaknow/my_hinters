# Self-proving protocol

Proof levels: **P0 Conjecture** (falsifiable); **P1 Supported** (event IDs, tick ranges, or snapshot files with SHA-256); **P2 Reproducible** (`analysis/` regenerates the result from archived data and `hglab prove` passes); **P3 Replicated** (independent role on a different runtime/model vendor or a fresh in-world run); **P4 Predictive** (prediction committed before `window_start_utc` and confirmed). Terminal statuses: Refuted and Superseded.

Self-review is not P3. Claims record `author_runtime` and `replicator_runtime`. Do not call anything a law below P4 in more than one context. Optionally timestamp at most one public prediction per day with `commit <ID> sha256:<16 hex>`.

Calibrate clock, energy, resource regeneration, and road savings before describing emergent behaviour. Preserve raw public event data only where permitted; do not persist raw observations containing private inbox/notebook fields.
