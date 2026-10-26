"""The NemoClaw side of the local environment: Docker, the OpenShell gateway, Ollama and the sandbox.

On Windows every command runs inside the WSL distribution named in ``config/local.yaml`` (``nemoclaw.wsl_distro``);
on Linux it runs in a login shell directly. ``stack_status`` reads, ``stack_up`` starts what is down, in the
order a reboot needs: Docker first (started by the desktop app or the system, never by us), then the gateway
user service, then the user-local Ollama daemon, then the sandbox and its doctor, then the dashboard forward.

The OpenClaw dashboard (``http://127.0.0.1:18789``) needs an OpenShell port forward. Onboarding starts one as a
background process, which dies with the shell that started it or with the WSL distribution, and nothing brought
it back: on 2026-10-26 the dashboard was down while the sandbox was Ready. ``ensure_dashboard`` installs the
forward as a systemd user service (``hinters-dashboard-forward``, restarted whenever it exits) and starts it;
the supervisor checks it every ``ecosystem.stack_every_minutes``. The user's services keep running without a
login session only with linger on (``loginctl enable-linger``).
"""

from __future__ import annotations

import base64
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
DASHBOARD_UNIT = "hinters-dashboard-forward"
DASHBOARD_PORT = 18789
NOISE = ("ExperimentalWarning", "trace-warnings")


def host_shell(config: dict[str, Any]) -> list[str]:
    """The prefix that runs a login shell where nemoclaw lives: wsl on Windows, bash on Linux."""
    nemoclaw = config.get("nemoclaw") or {}
    if platform.system() == "Windows":
        return ["wsl", "-d", str(nemoclaw.get("wsl_distro", "Ubuntu")), "-e", "bash", "-lc"]  # -e: no outer shell expands the script first ($vars, $(...))
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


def dashboard_port(config: dict[str, Any]) -> int:
    return int((config.get("nemoclaw") or {}).get("dashboard_port", DASHBOARD_PORT) or DASHBOARD_PORT)


def dashboard_unit(sandbox: str, port: int, openshell: str = "%h/.local/bin/openshell") -> str:
    """The systemd user unit that keeps the dashboard's port forward up (foreground, restarted when it exits)."""
    return (
        "[Unit]\n"
        f"Description=Forward the {sandbox} sandbox's OpenClaw dashboard to 127.0.0.1:{port} (hglab local)\n"
        f"After={GATEWAY_UNIT}.service\n"
        f"Wants={GATEWAY_UNIT}.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStartPre=-/bin/sh -c '{openshell} forward stop {port} {sandbox} >/dev/null 2>&1'\n"
        f"ExecStart={openshell} forward start {port} {sandbox}\n"
        "Restart=always\n"
        "RestartSec=10s\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _probe(port: int) -> str:
    return f'curl -s -m 5 -o /dev/null -w "%{{http_code}}" http://127.0.0.1:{port}/'


def dashboard_status(config: dict[str, Any], run: Runner | None = None) -> dict[str, Any]:
    """Whether the forward service runs and the dashboard answers (no command changes anything)."""
    run = run or make_runner(config)
    port = dashboard_port(config)
    _code, text = run(f"systemctl --user is-active {DASHBOARD_UNIT}; {_probe(port)}", 30)
    lines = text.splitlines()
    service = lines[0].strip() if lines else "unknown"
    answer = lines[-1].strip()[-3:] if len(lines) > 1 else "000"
    return {"dashboard": service, "dashboard_http": answer, "dashboard_url": f"http://127.0.0.1:{port}/", "dashboard_ok": service == "active" and answer not in ("000", "")}


def ensure_dashboard(config: dict[str, Any], run: Runner | None = None, say: Callable[[str], None] = print) -> dict[str, Any]:
    """Install (or update) the dashboard forward service, start it, and wait for the dashboard to answer."""
    nemoclaw = config.get("nemoclaw") or {}
    sandbox = str(nemoclaw.get("sandbox") or "")
    if not sandbox or nemoclaw.get("dashboard") is False:
        return {"dashboard": None}
    run = run or make_runner(config)
    port = dashboard_port(config)
    code, text = run("command -v openshell", 30)
    found = text.splitlines()[-1].strip() if code == 0 and text else ""
    openshell = found if found.startswith("/") else "%h/.local/bin/openshell"
    unit = dashboard_unit(sandbox, port, openshell)
    path = f"$HOME/.config/systemd/user/{DASHBOARD_UNIT}.service"
    script = (
        f"mkdir -p $HOME/.config/systemd/user && echo {base64.b64encode(unit.encode()).decode()} | base64 -d > {path}.new && "  # base64: no quote survives the trip through wsl.exe intact
        f"if cmp -s {path}.new {path}; then rm {path}.new; changed=0; else mv {path}.new {path}; systemctl --user daemon-reload; changed=1; fi; "
        f"systemctl --user enable {DASHBOARD_UNIT} >/dev/null 2>&1; "
        f"if [ $changed = 1 ]; then systemctl --user restart {DASHBOARD_UNIT}; else systemctl --user start {DASHBOARD_UNIT}; fi; "
        f"for i in $(seq 1 20); do c=$({_probe(port)}); [ \"$c\" != 000 ] && break; sleep 1; done; "
        f"echo changed=$changed; systemctl --user is-active {DASHBOARD_UNIT}; echo $c"
    )
    code, text = run(script, 120)
    lines = text.splitlines()
    status = {"dashboard": lines[-2].strip() if len(lines) >= 2 else "unknown", "dashboard_http": lines[-1].strip()[-3:] if lines else "000", "dashboard_url": f"http://127.0.0.1:{port}/"}
    status["dashboard_ok"] = status["dashboard"] == "active" and status["dashboard_http"] not in ("000", "")
    say(f"dashboard {'up' if status['dashboard_ok'] else 'not answering'} at {status['dashboard_url']} (forward service {status['dashboard']})")
    return status


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
    if nemoclaw.get("dashboard") is not False:
        out.update(dashboard_status(config, run))
    out["ok"] = (
        bool(out["docker"])
        and out["gateway"] == "active"
        and out["phase"] == "Ready"
        and out["openclaw"] == "running"
        and out.get("dashboard_ok", True)
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
    ensure_dashboard(config, run, say)
    return stack_status(config, run)


__all__ = [
    "DASHBOARD_PORT", "DASHBOARD_UNIT", "GATEWAY_UNIT", "OLLAMA_CHECK", "dashboard_status", "dashboard_unit", "ensure_dashboard",
    "host_shell", "make_runner", "stack_status", "stack_up",
]
