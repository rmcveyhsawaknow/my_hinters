"""Host backups: the local configuration, the supervisor state and a fresh graph snapshot in one tarball.

A backup is ``<host_id>-<utc>.tar.gz`` under ``runs/local/backups/`` holding ``config/local.yaml``,
``runs/local/status.json``, ``runs/local/supervisor.log``, the capability cards and ``memory.sqlite``
(a consistent SQLite backup), plus a ``manifest.json``. ``push`` copies it to a target: ``local:<dir>``
needs nothing; ``gs://bucket/prefix`` uses the installed ``gcloud storage`` command and lands under
``hosts/<host_id>/backups/``. ``restore`` unpacks one into a checkout that has no state yet (or with
``force``). Nothing secret is in a backup: keys live in the keyring, never in these files.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tarfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hglab.local.memory import Graph

BACKUP_DIR = Path("runs/local/backups")
STATE_FILES = ("config/local.yaml", "runs/local/status.json", "runs/local/supervisor.log")
Runner = Callable[[list[str]], tuple[int, str]]


def host_id(config: dict[str, Any]) -> str:
    eco = config.get("ecosystem") or {}
    return str(eco.get("host_id") or socket.gethostname().lower())


def default_target(root: Path, config: dict[str, Any]) -> str:
    eco = config.get("ecosystem") or {}
    return str(eco.get("backup_target") or f"local:{root / BACKUP_DIR}")


def _run(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def make_backup(root: Path, config: dict[str, Any], when: datetime | None = None) -> Path:
    """Write the tarball and return its path."""
    when = when or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    host = host_id(config)
    folder = root / BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{host}-{stamp}.tar.gz"
    manifest: dict[str, Any] = {"host": host, "utc": when.isoformat(), "files": []}
    graph_path = root / "runs/local/memory.sqlite"
    snapshot: Path | None = None
    if graph_path.is_file():
        graph = Graph(graph_path)
        try:
            snapshot = graph.snapshot(f"backup-{stamp}")
            manifest["graph"] = graph.counts()
        finally:
            graph.close()
    with tarfile.open(archive, "w:gz") as tar:
        for rel in STATE_FILES:
            path = root / rel
            if path.is_file():
                tar.add(path, arcname=rel)
                manifest["files"].append(rel)
        for card in sorted((root / "runs/local/cards").glob("*.json")):
            tar.add(card, arcname=f"runs/local/cards/{card.name}")
            manifest["files"].append(f"runs/local/cards/{card.name}")
        if snapshot is not None:
            tar.add(snapshot, arcname="runs/local/memory.sqlite")
            manifest["files"].append("runs/local/memory.sqlite")
        manifest_path = folder / f"{archive.stem}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tar.add(manifest_path, arcname="manifest.json")
        manifest_path.unlink()
    return archive


def push(
    root: Path, config: dict[str, Any], target: str | None = None, runner: Runner | None = None
) -> dict[str, Any]:
    """Make a backup and copy it to the target; returns what was done."""
    target = target or default_target(root, config)
    archive = make_backup(root, config)
    host = host_id(config)
    if target.startswith("gs://"):
        run = runner or _run
        destination = f"{target.rstrip('/')}/hosts/{host}/backups/{archive.name}"
        code, out = run(["gcloud", "storage", "cp", str(archive), destination])
        return {
            "archive": str(archive),
            "target": destination,
            "ok": code == 0,
            "detail": out[-400:],
        }
    folder = Path(target.removeprefix("local:"))
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / archive.name
    if destination.resolve() != archive.resolve():
        shutil.copy2(archive, destination)
    return {"archive": str(archive), "target": str(destination), "ok": destination.is_file()}


def list_backups(
    root: Path, config: dict[str, Any], target: str | None = None, runner: Runner | None = None
) -> list[dict[str, Any]]:
    target = target or default_target(root, config)
    if target.startswith("gs://"):
        run = runner or _run
        _code, out = run(
            [
                "gcloud",
                "storage",
                "ls",
                "-l",
                f"{target.rstrip('/')}/hosts/{host_id(config)}/backups/",
            ]
        )
        rows = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[-1].endswith(".tar.gz"):
                rows.append(
                    {
                        "name": parts[-1].rsplit("/", 1)[-1],
                        "size": int(parts[0]) if parts[0].isdigit() else None,
                        "utc": parts[1],
                        "location": parts[-1],
                    }
                )
        return sorted(rows, key=lambda r: r["name"], reverse=True)
    folder = Path(target.removeprefix("local:"))
    rows = []
    for path in sorted(folder.glob("*.tar.gz"), reverse=True) if folder.is_dir() else []:
        stamp = path.stem.replace(".tar", "").rsplit("-", 1)[-1]
        rows.append(
            {"name": path.name, "size": path.stat().st_size, "utc": stamp, "location": str(path)}
        )
    return rows


def latest_backup_utc(root: Path, config: dict[str, Any]) -> str | None:
    rows = list_backups(root, config, f"local:{root / BACKUP_DIR}")
    return rows[0]["utc"] if rows else None


def restore(root: Path, archive: Path, force: bool = False) -> dict[str, Any]:
    """Unpack a backup into a checkout: state files only where none exist (or with force); the graph likewise."""
    restored, skipped = [], []
    with tarfile.open(archive, "r:gz") as tar:
        members = [
            m
            for m in tar.getmembers()
            if m.isfile() and not m.name.startswith(("/", "..")) and ".." not in Path(m.name).parts
        ]
        for member in members:
            if member.name == "manifest.json":
                continue
            target = root / member.name
            if target.exists() and not force:
                skipped.append(member.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            restored.append(member.name)
    return {"archive": str(archive), "restored": restored, "skipped": skipped}


__all__ = [
    "BACKUP_DIR",
    "default_target",
    "host_id",
    "latest_backup_utc",
    "list_backups",
    "make_backup",
    "push",
    "restore",
]
