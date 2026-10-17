"""Fail when tracked text appears to contain an API key or credential."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    re.compile(r"hg_[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{24,}"),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(name) for name in result.stdout.splitlines() if Path(name).is_file()]


def scan(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append(f"{path}:{number}: possible credential")
    return findings


if __name__ == "__main__":
    results = scan([Path(arg) for arg in sys.argv[1:]]) if len(sys.argv) > 1 else scan(tracked_files())
    if results:
        print("\n".join(results), file=sys.stderr)
        raise SystemExit(1)
    print("No likely credentials found.")
