"""The NemoClaw side of the local environment: Docker, the OpenShell gateway, Ollama and the sandbox.

On Windows every command runs inside the WSL distribution named in ``config/local.yaml`` (``nemoclaw.wsl_distro``);
on Linux it runs in a login shell directly. ``stack_status`` reads, ``stack_up`` starts what is down, in the
order a reboot needs: Docker first (started by the desktop app or the system, never by us), then the gateway
user service, then the user-local Ollama daemon, then the sandbox and its doctor.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[[str, int], tuple[int, str]]

OLLAMA_CHECK = 'curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:11434/api/tags'
OLLAMA_START = (
    "mkdir -p ~/.local/state && "
    "(setsid nohup ~/.local/bin/ollama serve > ~/.local/state/ollama.log 2>&1 < /dev/null &) ; sleep 4; "
    + OLLAMA_CHECK
)
GATEWAY_UNIT = "nemoclaw-openshell-gateway"
NOISE = ("ExperimentalWarning", "trace-warnings")


def host_shell(config: dict[str, Any]) -> list[str]:
    """The prefix that runs a login shell where nemoclaw lives: wsl on Windows, bash on Linux."""
    nemoclaw = config.get("nemoclaw") or {}
    if platform.system() == "Windows":
        return ["wsl", "-d", str(nemoclaw.get("wsl_distro", "Ubuntu")), "--", "bash", "-lc"]
    return ["bash", "-lc"]


def make_runner(config: dict[str, Any]) -> Runner:
    prefix = host_shell(config)

    def run(script: str, timeout: int = 300) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                [*prefix, script], capture_output=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)
        raw = proc.stdout + proc.stderr
        text = (
            raw.decode("utf-16", "replace")
            if b"\x00" in raw[:8]
            else raw.decode("utf-8", "replace")
        )
        lines = [line.rstrip() for line in text.splitlines() if not any(n in line for n in NOISE)]
        return proc.returncode, "\n".join(lines).strip()

    return run


def docker_desktop_exe() -> Path | None:
    for base in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if (
            base
            and (candidate := Path(base) / "Docker" / "Docker" / "Docker Desktop.exe").is_file()
        ):
            return candidate
    return None


def start_docker_desktop(
    run: Runner, say: Callable[[str], None], wait_seconds: int = 180
) -> tuple[int, str]:
    """Launch Docker Desktop (Windows) and wait for the engine to answer inside WSL."""
    exe = docker_desktop_exe()
    if exe is None:
        say("Docker Desktop.exe not found under Program Files; start it by hand")
        return 1, ""
    try:
        subprocess.Popen(
            [str(exe)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        say(f"could not start Docker Desktop: {exc}")
        return 1, ""
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(10)
        code, text = run('docker info --format "{{.ServerVersion}}"', 60)
        if code == 0 and text:
            return code, text
    return 1, ""


def _field(text: str, label: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            return stripped[len(label) :].strip() or None
    return None


def stack_status(config: dict[str, Any], run: Runner | None = None) -> dict[str, Any]:
    """What is up on the NemoClaw side, as a plain dict (no command changes anything)."""
    nemoclaw = config.get("nemoclaw") or {}
    sandbox = str(nemoclaw.get("sandbox") or "")
    run = run or make_runner(config)
    out: dict[str, Any] = {"configured": bool(sandbox), "sandbox": sandbox or None}
    if not sandbox:
        return out
    code, text = run('docker info --format "{{.ServerVersion}}"', 60)
    out["docker"] = text.splitlines()[-1] if code == 0 and text else None
    code, text = run(f"systemctl --user is-active {GATEWAY_UNIT}", 30)
    out["gateway"] = text.splitlines()[-1] if text else "unknown"
    code, text = run(OLLAMA_CHECK, 20)
    out["ollama"] = text.strip()[-3:] == "200"
    code, text = run(f"nemoclaw {sandbox} status", 120)
    out["phase"] = _field(text, "Phase:")
    out["openclaw"] = _field(text, "OpenClaw:")
    out["model"] = _field(text, "Model:")
    out["provider"] = _field(text, "Provider:")
    out["inference"] = _field(text, "Inference:")
    out["ok"] = (
        bool(out["docker"])
        and out["gateway"] == "active"
        and out["phase"] == "Ready"
        and out["openclaw"] == "running"
    )
    return out


def stack_up(
    config: dict[str, Any], run: Runner | None = None, say: Callable[[str], None] = print
) -> dict[str, Any]:
    """Start what is down, in reboot order, and return the status afterwards."""
    nemoclaw = config.get("nemoclaw") or {}
    sandbox = str(nemoclaw.get("sandbox") or "")
    run = run or make_runner(config)
    if not sandbox:
        say("no nemoclaw.sandbox in config/local.yaml: nothing to bring up on that side")
        return {"configured": False}
    code, text = run('docker info --format "{{.ServerVersion}}"', 90)
    if (code != 0 or not text) and platform.system() == "Windows":
        say("Docker is not running: starting Docker Desktop and waiting for its engine")
        code, text = start_docker_desktop(run, say)
    if code != 0 or not text:
        say(
            "Docker is not running: start Docker Desktop (Windows) or the docker service (Linux), then run this again"
        )
        return {"configured": True, "docker": None, "ok": False}
    say(f"docker {text.splitlines()[-1]}")
    code, text = run(
        f"systemctl --user is-active {GATEWAY_UNIT} || systemctl --user start {GATEWAY_UNIT}; sleep 2; systemctl --user is-active {GATEWAY_UNIT}",
        60,
    )
    say(f"gateway {text.splitlines()[-1] if text else 'unknown'}")
    if nemoclaw.get("ollama", True):
        code, text = run(OLLAMA_CHECK, 20)
        if text.strip()[-3:] != "200":
            code, text = run(OLLAMA_START, 60)
        say(f"ollama {'up' if text.strip()[-3:] == '200' else 'not answering on 11434'}")
    code, text = run(f"nemoclaw {sandbox} start", 300)
    say(f"sandbox start: {text.splitlines()[-1] if text else 'no output'}")
    code, text = run(f"nemoclaw {sandbox} doctor --fix", 300)
    summary = _field(text, "Summary:")
    say(f"doctor: {summary or (text.splitlines()[-1] if text else 'no output')}")
    return stack_status(config, run)


__all__ = ["GATEWAY_UNIT", "OLLAMA_CHECK", "host_shell", "make_runner", "stack_status", "stack_up"]
