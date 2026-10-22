"""Host backups: the local configuration, the supervisor state and a fresh graph snapshot in one tarball.

A backup is ``<host_id>-<utc>.tar.gz`` under ``runs/local/backups/`` holding ``config/local.yaml``,
``runs/local/status.json``, ``runs/local/supervisor.log``, the capability cards and ``memory.sqlite``
(a consistent SQLite backup), plus a ``manifest.json``. ``push`` copies it to a target: ``local:<dir>``
needs nothing; ``gs://bucket/prefix`` lands under ``hosts/<host_id>/backups/`` and authenticates with
the host's service account key from the keyring (``GCP_SERVICE_ACCOUNT_KEY``, the default) or, when
``ecosystem.auth`` or ``HGLAB_GCP_AUTH`` says ``gcloud``, with the signed-in ``gcloud storage`` session.
``restore`` unpacks one into a checkout that has no state yet (or with ``force``). Nothing secret is in
a backup: keys live in the keyring, never in these files.
"""

from __future__ import annotations

import json
import os
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
AUTH_ENV = "HGLAB_GCP_AUTH"
AUTH_MODES = ("service_account", "gcloud")
Runner = Callable[[list[str]], tuple[int, str]]
ClientFactory = Callable[[dict[str, Any]], Any | None]


def host_id(config: dict[str, Any]) -> str:
    eco = config.get("ecosystem") or {}
    return str(eco.get("host_id") or socket.gethostname().lower())


def default_target(root: Path, config: dict[str, Any]) -> str:
    eco = config.get("ecosystem") or {}
    return str(eco.get("backup_target") or f"local:{root / BACKUP_DIR}")


def auth_mode(config: dict[str, Any]) -> str:
    """``service_account`` (the key in the keyring, the default) or ``gcloud`` (the signed-in session); the environment wins."""
    mode = os.environ.get(AUTH_ENV) or str(
        (config.get("ecosystem") or {}).get("auth") or "service_account"
    )
    return mode if mode in AUTH_MODES else "service_account"


def gcs_client(config: dict[str, Any]) -> Any | None:
    """A Storage client from the GCP_SERVICE_ACCOUNT_KEY in the keyring, or None when there is no key."""
    from hglab.secrets import get_secret

    raw = get_secret("GCP_SERVICE_ACCOUNT_KEY")
    if not raw:
        return None
    from google.cloud import storage
    from google.oauth2 import service_account

    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
    )
    return storage.Client(project=info.get("project_id"), credentials=credentials)


def _split_gs(target: str) -> tuple[str, str]:
    bucket, _, prefix = target.removeprefix("gs://").strip("/").partition("/")
    return bucket, prefix


def _run(args: list[str]) -> tuple[int, str]:
    """Run a tool by name; on Windows the Cloud SDK installs gcloud as a .cmd that needs resolving first."""
    resolved = shutil.which(args[0]) or args[0]
    try:
        proc = subprocess.run([resolved, *args[1:]], capture_output=True, text=True, check=False)
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
    root: Path,
    config: dict[str, Any],
    target: str | None = None,
    runner: Runner | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Make a backup and copy it to the target; returns what was done."""
    target = target or default_target(root, config)
    archive = make_backup(root, config)
    host = host_id(config)
    if target.startswith("gs://"):
        destination = f"{target.rstrip('/')}/hosts/{host}/backups/{archive.name}"
        mode = auth_mode(config)
        if mode == "service_account":
            client = (client_factory or gcs_client)(config)
            if client is None:
                return {
                    "archive": str(archive),
                    "target": destination,
                    "ok": False,
                    "auth": mode,
                    "detail": "no GCP_SERVICE_ACCOUNT_KEY in the keyring: store one with `hglab key store GCP_SERVICE_ACCOUNT_KEY --from-file <key.json>` or run with --auth gcloud",
                }
            bucket, prefix = _split_gs(target)
            path = f"{prefix}/hosts/{host}/backups/{archive.name}".strip("/")
            try:
                client.bucket(bucket).blob(path).upload_from_filename(str(archive))
            except Exception as exc:  # noqa: BLE001 - a backup reports, it never raises
                return {
                    "archive": str(archive),
                    "target": destination,
                    "ok": False,
                    "auth": mode,
                    "detail": str(exc)[:400],
                }
            return {"archive": str(archive), "target": destination, "ok": True, "auth": mode}
        run = runner or _run
        code, out = run(["gcloud", "storage", "cp", str(archive), destination])
        return {
            "archive": str(archive),
            "target": destination,
            "ok": code == 0,
            "auth": mode,
            "detail": out[-400:],
        }
    folder = Path(target.removeprefix("local:"))
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / archive.name
    if destination.resolve() != archive.resolve():
        shutil.copy2(archive, destination)
    return {"archive": str(archive), "target": str(destination), "ok": destination.is_file()}


def list_backups(
    root: Path,
    config: dict[str, Any],
    target: str | None = None,
    runner: Runner | None = None,
    client_factory: ClientFactory | None = None,
) -> list[dict[str, Any]]:
    target = target or default_target(root, config)
    if target.startswith("gs://"):
        folder = f"{_split_gs(target)[1]}/hosts/{host_id(config)}/backups/".strip("/") + "/"
        if auth_mode(config) == "service_account":
            client = (client_factory or gcs_client)(config)
            if client is None:
                return []
            bucket = _split_gs(target)[0]
            rows = []
            for blob in client.list_blobs(bucket, prefix=folder):
                if blob.name.endswith(".tar.gz"):
                    updated = getattr(blob, "updated", None)
                    rows.append(
                        {
                            "name": blob.name.rsplit("/", 1)[-1],
                            "size": blob.size,
                            "utc": updated.isoformat() if updated else None,
                            "location": f"gs://{bucket}/{blob.name}",
                        }
                    )
            return sorted(rows, key=lambda r: r["name"], reverse=True)
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
    folder_path = Path(target.removeprefix("local:"))
    rows = []
    for path in sorted(folder_path.glob("*.tar.gz"), reverse=True) if folder_path.is_dir() else []:
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
    "AUTH_ENV",
    "AUTH_MODES",
    "BACKUP_DIR",
    "auth_mode",
    "default_target",
    "gcs_client",
    "host_id",
    "latest_backup_utc",
    "list_backups",
    "make_backup",
    "push",
    "restore",
]
