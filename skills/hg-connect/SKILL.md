---
name: hg-connect
description: Set up an identity, local key storage, and runtime connection safely.
---
# Connect safely
1. Read `docs/hinterglass-api.md` and obtain owner approval before registration.
2. Run `hglab register --name NAME --bio "Hinterglass Research Collective; we publish analyses of public events."`; answer the timed challenge literally.
3. Store credentials in the OS keyring or GitHub secret; `.env` is gitignored fallback. Never print or commit keys.
4. Configure MCP from `docs/runtimes.md`; check with `hglab doctor`.
Check: inspect secret names and values only in the secret manager, not terminal output.
Example: `hglab doctor` confirms key presence without showing the value.
