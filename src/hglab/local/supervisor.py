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
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hglab.local.cron import matches

JOBS = ("tick", "shift", "keepalive", "crier", "land", "news")
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


ROUND_OFFSET = 30  # the office and collector rounds run this many minutes after the shift starts: a persona runs one job at a time
KEEPALIVE_OFFSET = 40  # after the shift has ended (the hands' shifts run about 36 minutes), before the next one


def due_jobs(persona: Any, when: datetime, entry: dict[str, Any]) -> list[str]:
    """Which of an agent's jobs are due at this minute, from its knobs (UTC) and its local entry.

    The shift starts at the work cron's minute. The land and collector rounds and the keepalive take
    their own minutes after it, because a persona never runs two jobs at once and a round due in the
    shift's minute was skipped every hour (the land round ran once and the collector round never
    between the cut-over and 2026-10-24).
    """
    jobs = set(entry.get("jobs") or ["tick", "shift", "keepalive", "crier", "land"])
    out: list[str] = []
    cadence = (persona.knobs.get("cadence") or {}).get("cron")
    work = (persona.knobs.get("work") or {}).get("cron")
    if "tick" in jobs and cadence and matches(str(cadence), when):
        out.append("tick")
    if work and matches(str(work), when) and "shift" in jobs:
        out.append("shift")
    if work:
        head = str(work).split()[0]
        minute = int(head.split(",")[0]) if head.replace(",", "").isdigit() else 3
        if when.minute == (minute + ROUND_OFFSET) % 60:
            if "crier" in jobs and persona.quirk.get("type") == "feature_watch":
                out.append("crier")
            if "land" in jobs and persona.knobs.get("stake_lots"):
                out.append("land")
        if "keepalive" in jobs and when.minute == (minute + KEEPALIVE_OFFSET) % 60:
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
    if job == "news":
        return [*base, "shift", "--agent", slug, "--max-wakes", "1", *(["--dry-run"] if dry_run else []), *flags]  # one wake: the news step runs first
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
        self.backup_runner: Any = None
        self.status_path = root / STATUS_FILE
        self.log_path = root / LOG_FILE
        self.status: dict[str, Any] = self._load_status()
        self._lock = threading.RLock()
        self._busy: set[str] = set()
        self._threads: list[threading.Thread] = []

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
        with self._lock:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status["updated_utc"] = datetime.now(UTC).isoformat()
            self.status_path.write_text(
                json.dumps(self.status, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _log(self, line: str) -> None:
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now(UTC).isoformat()} {line}\n")

    def _run_subprocess(self, command: list[str]) -> tuple[int, str]:
        env = {**os.environ, "PYTHONUTF8": "1", "HGLAB_RUNTIME": "local"}
        try:
            proc = subprocess.run(
                command,
                check=False,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # the child writes UTF-8; a console code page must never fail the job
                env=env,
                timeout=40 * 60,
            )
        except subprocess.TimeoutExpired as exc:
            tail = (exc.stdout or b"") + (exc.stderr or b"")
            text = tail.decode("utf-8", "replace") if isinstance(tail, bytes) else str(tail)
            return 124, f"timed out after 40 minutes\n{text}"[-4000:]
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-4000:]

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
        with self._lock:
            agent = self.status.setdefault("agents", {}).setdefault(slug, {"history": []})
            agent["last"] = record
            agent.setdefault("history", []).append(record)
            agent["history"] = agent["history"][-30:]
            self._save_status()
        self._log(f"{slug} {job} exit {code} in {record['seconds']}s: {summary}")
        for line in record.get("tail") or []:
            self._log(f"  | {line}")
        return record

    def tick(
        self, personas: dict[str, Any], when: datetime | None = None, wait: bool = False
    ) -> list[tuple[str, str]]:
        """One minute of the schedule: start every due job for every enabled agent, each in its own thread.

        A persona never runs two jobs at once (a shift takes twenty minutes; its tick waits for the
        next minute it is due), and one persona's long job never delays another's. ``wait`` joins the
        threads, for the CLI and the tests; the loop does not wait.
        """
        when = when or datetime.now(UTC)
        started: list[tuple[str, str]] = []
        self._threads = [t for t in self._threads if t.is_alive()]
        for entry in self.entries():
            slug = str(entry.get("slug"))
            persona = personas.get(slug)
            if persona is None:
                continue
            for job in due_jobs(persona, when, entry):
                with self._lock:
                    if slug in self._busy:
                        self._log(f"{slug} {job} skipped: a job is still running")
                        continue
                    self._busy.add(slug)
                thread = threading.Thread(
                    target=self._run_job, args=(slug, job, entry.get("dry_run", None)), daemon=True
                )
                thread.start()
                self._threads.append(thread)
                started.append((slug, job))
        if wait:
            for thread in self._threads:
                thread.join()
        return started

    def _run_job(self, slug: str, job: str, dry_run: bool | None) -> None:
        try:
            self.run_once(slug, job, dry_run)
        finally:
            with self._lock:
                self._busy.discard(slug)

    def backup(self, personas: dict[str, Any]) -> dict[str, Any]:
        """Write the capability cards and push a backup to the configured target; never raises."""
        from hglab.local.backup import push
        from hglab.local.cards import write_cards
        from hglab.persona import load_teams

        try:
            write_cards(self.root, personas, load_teams(self.root), self.config)
            result = (
                self.backup_runner(self.root, self.config)
                if self.backup_runner
                else push(self.root, self.config)
            )
        except Exception as exc:  # noqa: BLE001 - a backup must never stop the supervisor
            result = {"ok": False, "detail": str(exc)[:300]}
        self.status["last_backup"] = {
            "utc": datetime.now(UTC).isoformat(),
            **{k: result.get(k) for k in ("ok", "archive", "target", "detail") if k in result},
        }
        self._save_status()
        self._log(
            f"backup {'ok' if result.get('ok') else 'FAILED'}: {result.get('target') or result.get('detail', '')}"
        )
        return result

    def adapt(self, personas: dict[str, Any]) -> dict[str, Any]:
        """Recompute every persona's assignment from the local evidence and brief the ones that changed; never raises."""
        from hglab.local.goals import adapt, brief
        from hglab.local.memory import Graph
        from hglab.persona import load_teams

        graph_path = self.root / "runs/local/memory.sqlite"
        try:
            graph = Graph(graph_path)
            try:
                try:
                    from hglab.local.measure import refresh_archive, refresh_pulse

                    archive = refresh_archive(self.root)
                    pulse = refresh_pulse(self.root, list(personas))
                    self._log(
                        f"measure ok: archive +{archive.get('added', 0)} ({archive.get('total', 0)} events to tick {archive.get('newest_tick', 0)}),"
                        f" pulse for {len(pulse.get('agents', []))} persona(s)"
                    )
                except Exception as exc:  # noqa: BLE001 - measurement is a bonus of the cycle; the assignments still follow
                    self._log(f"measure skipped: {str(exc)[:160]}")
                try:
                    from hglab.architecture import ingest_architectures, refresh
                    from hglab.client import HinterglassClient

                    cat, _new = refresh(self.root, HinterglassClient(api_key=""), 7)  # reads the archive the measurement just refreshed
                    ingest_architectures(graph, cat)
                except Exception as exc:  # noqa: BLE001 - the catalogue is a bonus of the cycle
                    self._log(f"architecture catalogue skipped: {str(exc)[:160]}")
                plan = adapt(self.root, graph, personas, load_teams(self.root))
                briefed = brief(self.root, graph, plan)
            finally:
                graph.close()
            result = {
                "ok": True,
                "assigned": sum(1 for a in plan["agents"].values() if a.get("assignment")),
                "stalled": sorted(s for s, a in plan["agents"].items() if (a.get("assignment") or {}).get("stalled")),
                "briefed": briefed,
            }
        except Exception as exc:  # noqa: BLE001 - adaptation must never stop the supervisor
            result = {"ok": False, "detail": str(exc)[:300]}
        with self._lock:
            self.status["last_adapt"] = {"utc": datetime.now(UTC).isoformat(), **result}
            self._save_status()
        self._log(
            f"adapt {'ok' if result.get('ok') else 'FAILED'}: {result.get('assigned', result.get('detail', ''))} assignment(s), briefed {', '.join(result.get('briefed') or []) or 'nobody'}"
            + (f", stalled {', '.join(result['stalled'])}" if result.get("stalled") else "")
        )
        return result

    def watch(self, personas: dict[str, Any]) -> dict[str, Any]:
        """One look at the game's surface (keyless); when changes wait, the crier gets a news wake at once."""
        from hglab.client import HinterglassClient
        from hglab.features import pending_news, watch

        try:
            result = watch(self.root, HinterglassClient())
            pending = pending_news(self.root)
            found = result.get("discoveries") or []
            summary: dict[str, Any] = {
                "ok": True,
                "api_version": result.get("api_version"),
                "tick": result.get("tick"),
                "discoveries": len(found),
                "pending": len(pending),
                "utc": datetime.now(UTC).isoformat(),
            }
            line = f"watch ok: API {result.get('api_version')}, {len(found)} change(s), {len(pending)} pending"
            if found:
                line += ": " + "; ".join(str(d.get("text", ""))[:90] for d in found[:3])
            self._log(line)
            if pending:
                for entry in self.entries():
                    slug = str(entry.get("slug"))
                    persona = personas.get(slug)
                    if persona is None or persona.quirk.get("type") != "feature_watch":
                        continue
                    with self._lock:
                        if slug in self._busy:
                            self._log(f"{slug} news job waits: a job is still running")
                            continue
                        self._busy.add(slug)
                    thread = threading.Thread(target=self._run_job, args=(slug, "news", entry.get("dry_run", None)), daemon=True)
                    thread.start()
                    self._threads.append(thread)
                    self._log(f"{slug} news job started: {len(pending)} discovery(ies) pending")
                    summary["news_job"] = slug
        except Exception as exc:  # noqa: BLE001 - the watch must never stop the supervisor
            summary = {"ok": False, "detail": str(exc)[:300], "utc": datetime.now(UTC).isoformat()}
            self._log(f"watch FAILED: {summary['detail'][:160]}")
        with self._lock:
            self.status["last_watch"] = summary
            self._save_status()
        return summary

    def keep_dashboard(self) -> dict[str, Any]:
        """The NemoClaw dashboard's forward: restarted (and its service installed) when it is not answering."""
        from hglab.local.stack import dashboard_status, ensure_dashboard

        try:
            status = dashboard_status(self.config)
            if not status.get("dashboard_ok"):
                status = ensure_dashboard(self.config, say=lambda line: self._log(f"stack: {line}"))
        except Exception as exc:  # noqa: BLE001 - a broken check never stops the supervisor
            status = {"dashboard": "error", "error": str(exc)[:200]}
        self.status["dashboard"] = status
        self._save_status()
        return status

    def loop(self, personas: dict[str, Any], minutes: int | None = None) -> None:
        self._log(
            f"supervisor up: {', '.join(e.get('slug', '?') for e in self.entries())} (dry_run={self.config.get('dry_run', True)})"
        )
        self.status["running"] = True
        self._save_status()
        last_minute = None
        count = 0
        last_backup: datetime | None = None
        every = int((self.config.get("ecosystem") or {}).get("backup_every_minutes", 0) or 0)
        adapt_every = int((self.config.get("ecosystem") or {}).get("adapt_every_minutes", 0) or 0)
        last_adapt: datetime | None = None
        watch_every = int((self.config.get("ecosystem") or {}).get("watch_every_minutes", 10) or 0)
        last_watch: datetime | None = None
        stack_every = int((self.config.get("ecosystem") or {}).get("stack_every_minutes", 15) or 0) if (self.config.get("nemoclaw") or {}).get("sandbox") else 0
        last_stack: datetime | None = None
        try:
            while minutes is None or count < minutes:
                now = datetime.now(UTC).replace(second=0, microsecond=0)
                if now != last_minute:
                    last_minute = now
                    count += 1
                    self.tick(personas, now)
                    if every and (
                        last_backup is None or (now - last_backup).total_seconds() >= every * 60
                    ):
                        last_backup = now
                        threading.Thread(target=self.backup, args=(personas,), daemon=True).start()
                    if adapt_every and (
                        last_adapt is None or (now - last_adapt).total_seconds() >= adapt_every * 60
                    ):
                        last_adapt = now
                        threading.Thread(target=self.adapt, args=(personas,), daemon=True).start()
                    if watch_every and (
                        last_watch is None or (now - last_watch).total_seconds() >= watch_every * 60
                    ):
                        last_watch = now
                        threading.Thread(target=self.watch, args=(personas,), daemon=True).start()
                    if stack_every and (
                        last_stack is None or (now - last_stack).total_seconds() >= stack_every * 60
                    ):
                        last_stack = now
                        threading.Thread(target=self.keep_dashboard, daemon=True).start()
                time.sleep(5)
        finally:
            self.status["running"] = False
            self._save_status()
            self._log("supervisor down")


__all__ = ["JOBS", "Supervisor", "command_for", "due_jobs", "load_local_config"]
