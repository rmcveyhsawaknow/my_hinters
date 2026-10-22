"""Start the local environment at logon: a Startup-folder script on Windows, a systemd user unit on Linux.

Both run ``python -m hglab local up`` from the repository with the interpreter of the current virtual
environment, a minute after logon so Docker is up first, and append their output to ``runs/local/up.log``.
The Windows script needs no elevation (a Scheduled Task at logon does); the Linux unit starts at boot once
``loginctl enable-linger`` is set. ``render_*`` build the script and the unit so tests can check them without
touching the system; ``install``, ``remove`` and ``status`` touch the user's own files and systemd only.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_NAME = "hinters-local.cmd"
UNIT_NAME = "hinters-local.service"


def startup_folder() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def render_windows_startup_script(root: Path, python: str | None = None) -> str:
    python = python or sys.executable
    log = root / "runs" / "local" / "up.log"
    return (
        "@echo off\r\n"
        "rem The collective's local agents environment, written by `hglab local service install`.\r\n"
        "rem Waits a minute for Docker Desktop, then runs `hglab local up` in a minimised window.\r\n"
        "timeout /t 60 /nobreak >nul\r\n"
        f'start "hinters-local" /min cmd /c "cd /d "{root}" && "{python}" -m hglab local up >> "{log}" 2>&1"\r\n'
    )


def render_systemd_unit(root: Path, python: str | None = None) -> str:
    python = python or sys.executable
    return (
        "[Unit]\n"
        "Description=the collective's local agents environment (hglab local up)\n"
        "After=network-online.target docker.service\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={root}\n"
        f"ExecStart={python} -m hglab local up\n"
        "Restart=on-failure\n"
        "RestartSec=30\n"
        "Environment=PYTHONUTF8=1\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _run(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _last_run(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    log = root / "runs" / "local" / "up.log"
    if log.is_file():
        lines = [
            line
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        out["log"] = str(log)
        out["last_line"] = lines[-1][:160] if lines else None
    status_path = root / "runs" / "local" / "status.json"
    if status_path.is_file():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            out["supervisor_running"] = bool(data.get("running"))
            out["supervisor_updated_utc"] = data.get("updated_utc")
        except json.JSONDecodeError:
            pass
    return out


def install(root: Path, python: str | None = None) -> dict[str, Any]:
    (root / "runs" / "local").mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        folder = startup_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / SCRIPT_NAME
        path.write_text(render_windows_startup_script(root, python), encoding="utf-8")
        return {
            "kind": "windows-startup",
            "name": SCRIPT_NAME,
            "ok": path.is_file(),
            "path": str(path),
        }
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / UNIT_NAME
    unit_path.write_text(render_systemd_unit(root, python), encoding="utf-8")
    code, out = _run(["systemctl", "--user", "daemon-reload"])
    code2, out2 = _run(["systemctl", "--user", "enable", "--now", UNIT_NAME])
    return {
        "kind": "systemd-user",
        "name": UNIT_NAME,
        "ok": code == 0 and code2 == 0,
        "detail": (out + "\n" + out2).strip(),
        "path": str(unit_path),
        "hint": "run `loginctl enable-linger $USER` once so the unit starts at boot without a login",
    }


def remove(root: Path) -> dict[str, Any]:
    if platform.system() == "Windows":
        path = startup_folder() / SCRIPT_NAME
        existed = path.is_file()
        if existed:
            path.unlink()
        return {"kind": "windows-startup", "name": SCRIPT_NAME, "ok": True, "removed": existed}
    unit_path = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    code, out = _run(["systemctl", "--user", "disable", "--now", UNIT_NAME])
    if unit_path.is_file():
        unit_path.unlink()
    code2, out2 = _run(["systemctl", "--user", "daemon-reload"])
    return {
        "kind": "systemd-user",
        "name": UNIT_NAME,
        "ok": code == 0 and code2 == 0,
        "detail": (out + "\n" + out2).strip(),
    }


def status(root: Path) -> dict[str, Any]:
    if platform.system() == "Windows":
        path = startup_folder() / SCRIPT_NAME
        return {
            "kind": "windows-startup",
            "name": SCRIPT_NAME,
            "installed": path.is_file(),
            "path": str(path),
            **_last_run(root),
        }
    code, enabled = _run(["systemctl", "--user", "is-enabled", UNIT_NAME])
    _, active = _run(["systemctl", "--user", "is-active", UNIT_NAME])
    return {
        "kind": "systemd-user",
        "name": UNIT_NAME,
        "installed": code == 0,
        "enabled": enabled,
        "active": active,
        **_last_run(root),
    }


__all__ = [
    "SCRIPT_NAME",
    "UNIT_NAME",
    "install",
    "remove",
    "render_systemd_unit",
    "render_windows_startup_script",
    "startup_folder",
    "status",
]
