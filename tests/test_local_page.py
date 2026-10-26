"""The status page answers fast, and the NemoClaw dashboard's forward is a service that comes back (2026-10-26)."""

import json
import os
import platform


def test_the_dashboard_forward_is_a_service_that_comes_back():
    from hglab.local import stack

    unit = stack.dashboard_unit("hinters", 18789, "/home/u/.local/bin/openshell")
    assert "ExecStart=/home/u/.local/bin/openshell forward start 18789 hinters" in unit and "Restart=always" in unit and "WantedBy=default.target" in unit
    assert "forward start -d" not in unit  # in the foreground: a background forward died with the shell that started it
    config = {"nemoclaw": {"sandbox": "hinters"}}
    scripts = []

    def run(script, timeout=0):
        scripts.append(script)
        if script.startswith("command -v"):
            return 0, "/home/u/.local/bin/openshell"
        if "base64 -d" in script:
            return 0, "changed=1\nactive\n200"
        if "is-active hinters-dashboard-forward" in script:
            return 0, "inactive\n000"
        return 1, ""

    said = []
    up = stack.ensure_dashboard(config, run, said.append)
    assert up["dashboard_ok"] and up["dashboard_url"] == "http://127.0.0.1:18789/" and "dashboard up" in said[0]
    assert any("systemctl --user enable hinters-dashboard-forward" in s for s in scripts)
    assert stack.dashboard_status(config, run)["dashboard_ok"] is False  # down: the supervisor installs and starts it again
    assert stack.ensure_dashboard({"nemoclaw": {"sandbox": "hinters", "dashboard": False}}, run) == {"dashboard": None}


def test_wsl_runs_the_script_without_an_outer_shell():
    """`wsl -- bash -lc` let the distribution's shell expand $vars and $(...) first; `-e` hands the script to bash untouched."""
    from hglab.local.stack import host_shell

    prefix = host_shell({"nemoclaw": {"wsl_distro": "Ubuntu"}})
    if platform.system() == "Windows":
        assert prefix == ["wsl", "-d", "Ubuntu", "-e", "bash", "-lc"]
    else:
        assert prefix == ["bash", "-lc"]


def test_the_latest_record_reads_only_the_newest_files(tmp_path, monkeypatch):
    from hglab.local import goals

    day = tmp_path / "runs" / "2026-10-26"
    day.mkdir(parents=True)
    for i in range(300):
        path = day / f"Clarion-{i:04d}.json"
        path.write_text(json.dumps({"created_utc": f"2026-10-26T{i // 60:02d}:{i % 60:02d}:00+00:00", "approach": "build", "n": i}), encoding="utf-8")
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
    keep = day / "Clarion-keepalive-9.json"
    keep.write_text(json.dumps({"created_utc": "2026-10-26T23:59:00+00:00", "kind": "keepalive"}), encoding="utf-8")
    os.utime(keep, (1_700_001_000, 1_700_001_000))
    reads = []
    real = goals._read_record
    monkeypatch.setattr(goals, "_read_record", lambda path: reads.append(path) or real(path))
    assert goals.latest_record(tmp_path, "Clarion", "town-crier", planned=True)["n"] == 299
    assert len(reads) <= goals.RECORD_WINDOW  # a handful of files, not three days of them (13,600 on 2026-10-26)
    assert goals.latest_record(tmp_path, "Clarion", "town-crier")["kind"] == "keepalive"


def test_a_render_is_shared_and_reused_for_a_few_seconds():
    from hglab.local.ui import RenderCache

    calls = []
    cache = RenderCache(seconds=60)
    first = cache.get("page", lambda: calls.append(1) or b"one")
    again = cache.get("page", lambda: calls.append(1) or b"two")
    assert first == again == b"one" and len(calls) == 1
    stale = RenderCache(seconds=0)
    stale.get("page", lambda: b"one")
    assert stale.get("page", lambda: b"two") == b"two"
