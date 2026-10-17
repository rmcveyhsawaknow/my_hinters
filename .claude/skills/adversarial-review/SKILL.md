---
name: adversarial-review
description: Try to break a claim, analysis, or change before it is published.
---
# Review adversarially
1. Restate the claim and identify its strongest alternative explanation.
2. Check data provenance, leakage, preregistration timing, confounds, and assumptions.
3. Re-run analysis independently; vary sensible exclusions and parameters.
4. Report falsifying evidence and proof level, not just a list of improvements.
CLI: reproduce a claim with `hglab prove CLAIM-ID`.
Check: author self-review is not independent replication.
Example: shuffle event labels and test whether the reported association survives.
