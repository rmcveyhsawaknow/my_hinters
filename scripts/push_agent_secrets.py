"""Give GitHub Actions what every agent's caller workflow names, for the hand-over while this host is away.

For each persona, the caller (.github/workflows/agent-<slug>.yml) names an identity secret HG_KEY_<NAME>
and a switch variable HG_AGENT_<NAME>. Whatever is missing on GitHub is set: the secret from this host's
keyring, passed to `gh secret set` on stdin and never printed; the variable to `on`. The owner runs this
(skills/hg-deploy-agent); `--check` only lists what is missing.

    .venv\\Scripts\\python.exe scripts\\push_agent_secrets.py --check
    .venv\\Scripts\\python.exe scripts\\push_agent_secrets.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from hglab.persona import load_personas
from hglab.secrets import get_api_key


def main(check: bool) -> int:
    root = Path.cwd()
    secrets = set(subprocess.run(["gh", "secret", "list", "--json", "name", "-q", ".[].name"], capture_output=True, text=True, check=True).stdout.split())
    variables = {line.split("\t")[0] for line in subprocess.run(["gh", "variable", "list"], capture_output=True, text=True, check=True).stdout.splitlines() if line}
    failed = 0
    for slug, persona in sorted(load_personas(root).items()):
        caller = (root / ".github/workflows" / f"agent-{slug}.yml").read_text(encoding="utf-8")
        secret = re.search(r"secrets\.(HG_KEY_[A-Z0-9_]+)", caller).group(1)
        switch = re.search(r"vars\.(HG_AGENT_[A-Z0-9_]+)", caller).group(1)
        notes = []
        if secret in secrets:
            notes.append(f"{secret} present")
        elif check:
            notes.append(f"{secret} MISSING")
        elif not (value := get_api_key(persona.name, root)):
            notes.append(f"{secret} MISSING and no key in this host's keyring")
            failed += 1
        else:
            done = subprocess.run(["gh", "secret", "set", secret], check=False, input=value, capture_output=True, text=True)
            notes.append(f"{secret} set" if done.returncode == 0 else f"{secret} FAILED: {done.stderr.strip()[:80]}")
            failed += done.returncode != 0
        if switch in variables:
            notes.append(f"{switch} present")
        elif check:
            notes.append(f"{switch} MISSING")
        else:
            done = subprocess.run(["gh", "variable", "set", switch, "--body", "on"], check=False, capture_output=True, text=True)
            notes.append(f"{switch} on" if done.returncode == 0 else f"{switch} FAILED: {done.stderr.strip()[:80]}")
            failed += done.returncode != 0
        print(f"{slug:20} {persona.name:13} " + " | ".join(notes))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))
