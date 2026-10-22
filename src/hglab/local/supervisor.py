"""The local supervisor: the personas' own cadence, run on this machine in seconds.

It reads ``config/local.yaml`` (which agents run here, whether live or dry) and each persona's knobs
(``cadence.cron`` for character wakes, ``work.cron`` for shifts, the keepalive 33 minutes after the
shift's minute, the office rounds with the shift), decides each minute what is due, and runs the
same ``hglab`` commands GitHub Actions runs, as subprocesses so a crash or an outage ends one job,
not the supervisor. The world's notebook lease still makes two runtimes take turns for one agent,
so an agent may run here and on Actions during a migration. Every job's outcome goes to
``runs/local/status.json`` and ``runs/local/supervisor.log``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hglab.local.cron import matches

JOBS = ("tick", "shift", "keepalive", "crier", "land")
STATUS_FILE = Path("runs/local/status.json")
LOG_FILE = Path("runs/local/supervisor.log")


def load_local_config(root: Path) -> dict[str, Any]:
    path = root / "config/local.yaml"
    if not path.is_file():
        return {"agents": [], "dry_run": True, "a2a_port": 8765, "ui_port": 8766}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("agents", [])
    data.setdefault("dry_run", True)
    data.setdefault("a2a_port", 8765)
    data.setdefault("ui_port", 8766)
    return data


def due_jobs(persona: Any, when: datetime, entry: dict[str, Any]) -> list[str]:
    """Which of an agent's jobs are due at this minute, from its knobs (UTC) and its local entry."""
    jobs = set(entry.get("jobs") or ["tick", "shift", "keepalive", "crier", "land"])
    out: list[str] = []
    cadence = (persona.knobs.get("cadence") or {}).get("cron")
    work = (persona.knobs.get("work") or {}).get("cron")
    if "tick" in jobs and cadence and matches(str(cadence), when):
        out.append("tick")
    if work and matches(str(work), when):
        if "shift" in jobs:
            out.append("shift")
        if "crier" in jobs and persona.quirk.get("type") == "feature_watch":
            out.append("crier")
        if "land" in jobs and persona.knobs.get("stake_lots"):
            out.append("land")
    if "keepalive" in jobs and work:
        minute = (
            int(str(work).split()[0].split(",")[0])
            if str(work).split()[0].replace(",", "").isdigit()
            else 3
        )
        if when.minute == (minute + 33) % 60:
            out.append("keepalive")
    return out


def command_for(job: str, slug: str, dry_run: bool) -> list[str]:
    base = [sys.executable, "-m", "hglab"]
    flags = ["--scheduled"]
    if job == "tick":
        return [*base, "tick", "--agent", slug, *(["--dry-run"] if dry_run else []), *flags]
    if job == "shift":
        return [*base, "shift", "--agent", slug, *(["--dry-run"] if dry_run else []), *flags]
    if job == "keepalive":
        return [*base, "keepalive", "--agent", slug, *flags]
    if job == "crier":
        return [
            *base,
            "crier",
            "round",
            "--agent",
            slug,
            *(["--dry-run"] if dry_run else []),
            *flags,
        ]
    if job == "land":
        return [
            *base,
            "land",
            "round",
            "--agent",
            slug,
            *(["--dry-run"] if dry_run else []),
            *flags,
        ]
    raise ValueError(f"unknown job {job}")


class Supervisor:
    def __init__(
        self, root: Path, config: dict[str, Any] | None = None, runner: Any = None
    ) -> None:
        self.root = root
        self.config = config or load_local_config(root)
        self.runner = runner or self._run_subprocess
        self.status_path = root / STATUS_FILE
        self.log_path = root / LOG_FILE
        self.status: dict[str, Any] = self._load_status()

    def _load_status(self) -> dict[str, Any]:
        if self.status_path.is_file():
            try:
                return json.loads(self.status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {
            "agents": {},
            "started_utc": datetime.now(UTC).isoformat(),
            "host": os.environ.get("COMPUTERNAME") or os.uname().nodename
            if hasattr(os, "uname")
            else os.environ.get("COMPUTERNAME", "local"),
        }

    def _save_status(self) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status["updated_utc"] = datetime.now(UTC).isoformat()
        self.status_path.write_text(
            json.dumps(self.status, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _log(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()} {line}\n")

    def _run_subprocess(self, command: list[str]) -> tuple[int, str]:
        env = {**os.environ, "PYTHONUTF8": "1", "HGLAB_RUNTIME": "local"}
        proc = subprocess.run(
            command,
            check=False,
            cwd=str(self.root),
            capture_output=True,
            text=True,
            env=env,
            timeout=40 * 60,
        )
        return proc.returncode, (proc.stdout + proc.stderr)[-4000:]

    def entries(self) -> list[dict[str, Any]]:
        return [
            e
            for e in self.config.get("agents", [])
            if isinstance(e, dict) and e.get("enabled", True)
        ]

    def run_once(self, slug: str, job: str, dry_run: bool | None = None) -> dict[str, Any]:
        dry = self.config.get("dry_run", True) if dry_run is None else dry_run
        command = command_for(job, slug, dry)
        started = datetime.now(UTC)
        code, output = self.runner(command)
        finished = datetime.now(UTC)
        summary = next(
            (line for line in reversed(output.strip().splitlines()) if line.strip()), ""
        )[:300]
        record = {
            "job": job,
            "dry_run": dry,
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "seconds": round((finished - started).total_seconds(), 1),
            "exit": code,
            "summary": summary,
        }
        if code != 0:
            record["tail"] = [line[:200] for line in output.strip().splitlines()[-12:]]
        agent = self.status.setdefault("agents", {}).setdefault(slug, {"history": []})
        agent["last"] = record
        agent.setdefault("history", []).append(record)
        agent["history"] = agent["history"][-30:]
        self._save_status()
        self._log(f"{slug} {job} exit {code} in {record['seconds']}s: {summary}")
        for line in record.get("tail") or []:
            self._log(f"  | {line}")
        return record

    def tick(self, personas: dict[str, Any], when: datetime | None = None) -> list[tuple[str, str]]:
        """One minute of the schedule: run every due job for every enabled agent."""
        when = when or datetime.now(UTC)
        ran: list[tuple[str, str]] = []
        for entry in self.entries():
            slug = str(entry.get("slug"))
            persona = personas.get(slug)
            if persona is None:
                continue
            for job in due_jobs(persona, when, entry):
                self.run_once(slug, job, entry.get("dry_run", None))
                ran.append((slug, job))
        return ran

    def loop(self, personas: dict[str, Any], minutes: int | None = None) -> None:
        self._log(
            f"supervisor up: {', '.join(e.get('slug', '?') for e in self.entries())} (dry_run={self.config.get('dry_run', True)})"
        )
        self.status["running"] = True
        self._save_status()
        last_minute = None
        count = 0
        try:
            while minutes is None or count < minutes:
                now = datetime.now(UTC).replace(second=0, microsecond=0)
                if now != last_minute:
                    last_minute = now
                    count += 1
                    self.tick(personas, now)
                time.sleep(5)
        finally:
            self.status["running"] = False
            self._save_status()
            self._log("supervisor down")


__all__ = ["JOBS", "Supervisor", "command_for", "due_jobs", "load_local_config"]
