---
name: kb-curation
description: Create, validate, deduplicate, and index knowledge-base items.
---
# Curate knowledge
1. Use IDs `<PREFIX>-<YYYYMMDD>-<slug>` and the type-specific template.
2. Link evidence and related items; retain status and author runtime.
3. Run `hglab kb validate` and `hglab kb index`.
4. Preserve superseded history and keep the index current.
Check: front matter matches `schemas/kb-item.json`.
Example: `hglab kb new hypothesis "Roads reduce travel energy"` then complete prediction/falsifier.
