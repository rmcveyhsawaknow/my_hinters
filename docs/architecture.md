# Architecture

Python 3.12 package `hglab` is the portable CLI used by local runtimes and Actions. It separates world I/O, action validation, LLM routing, leases, redacted run records, and evidence curation. Canonical role and skill assets live in `roles/` and `skills/`; `hglab sync` generates Claude Code copies. The `kb/` stores hypotheses, methods, claims, and journals. Public data collected by the observatory is archived for scripts in `analysis/` and checked by `hglab prove`.

Agent workflows are separately gated by `HG_ENABLED=true`. CI has no secrets and mocks network interactions. Science-digest automation proposes changes but never merges.
