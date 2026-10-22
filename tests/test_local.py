import json
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from hglab.local.a2a import TaskStore, agent_card, make_handler
from hglab.local.cron import matches, parse
from hglab.local.memory import Graph, ingest_personas, ingest_public_events, ingest_record
from hglab.local.supervisor import Supervisor, command_for, due_jobs
from hglab.local.ui import render
from hglab.persona import load_personas, load_teams

ROOT = Path(__file__).resolve().parents[1]


def test_the_cron_matcher_reads_the_personas_knobs():
    assert parse("23 1,4,7,10,13,16,19,22 * * *")[1] == {1, 4, 7, 10, 13, 16, 19, 22}
    assert matches("23 1,4,7 * * *", datetime(2026, 10, 22, 4, 23, tzinfo=UTC))
    assert not matches("23 1,4,7 * * *", datetime(2026, 10, 22, 5, 23, tzinfo=UTC))
    assert matches("*/15 * * * 0", datetime(2026, 10, 25, 9, 45, tzinfo=UTC))  # a Sunday
    assert matches("0 0 1-7/2 * 7", datetime(2026, 11, 1, 0, 0, tzinfo=UTC))


def test_the_graph_keeps_nodes_edges_and_snapshots(tmp_path):
    g = Graph(tmp_path / "memory.sqlite")
    g.upsert_node("agent", "Clarion", team="square")
    g.upsert_node("agent", "Clarion", tick=10, roles=["navigator"])
    assert g.node("Clarion") == {
        "id": "Clarion",
        "kind": "agent",
        "tick": 10,
        "team": "square",
        "roles": ["navigator"],
    }
    assert g.add_edge(
        "Clarion", "Fudgewright", "whispered", 46182, text="hello"
    ) and not g.add_edge("Clarion", "Fudgewright", "whispered", 46182, text="hello")
    g.add_edge(
        "LandBroker", "Fudgewright", "promised", 46182, about="lot:I08-SE", what="survey and deed"
    )
    assert g.promises("Fudgewright") and g.promises("LandBroker")[0]["about"] == "lot:I08-SE"
    g.add_edge("LandBroker", "Fudgewright", "kept", 46900, about="lot:I08-SE", what="deed")
    assert g.promises("LandBroker") == []
    contacts = g.contacts("Fudgewright")
    assert set(contacts) == {"Clarion", "LandBroker"} and contacts["Clarion"]["received"] == 1
    path = g.snapshot("first")
    assert path.is_file() and g.snapshots()[0]["name"] == "first"
    g.add_edge("Clarion", "Quill", "gave", 47000, item="wood", qty=3)
    assert g.counts()["edges"]["gave"] == 1
    g.restore("first")
    assert "gave" not in g.counts()["edges"]
    assert g.query("select kind, count(*) as n from edges group by kind")[0]["n"] >= 1
    try:
        g.query("delete from edges")
    except ValueError as exc:
        assert "SELECT" in str(exc)
    g.close()


def test_records_and_public_events_become_edges(tmp_path):
    g = Graph(tmp_path / "memory.sqlite")
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    ingest_personas(g, personas, teams)
    assert g.node("Clarion")["team"] == "square" and g.node("team:neverland")["name"] == "Neverland"
    record = {
        "run_id": "r1",
        "agent": "LandBroker",
        "tick": 46182,
        "kind": "land_round",
        "actions": [
            {"action": "whisper", "to": "Fudgewright", "text": "SITE for factory: lot I08-SE"},
            {"action": "say", "text": "Survey for Fudgewright: lot I08-SE"},
        ],
        "reasons": ["survey for Fudgewright: lot I08-SE (ore-rich) at 45 wood"],
    }
    assert (
        ingest_record(g, record) == 4 and ingest_record(g, record) == 0
    )  # whisper and promise; never twice
    assert (
        g.promises("LandBroker")[0]["about"] == "lot:I08-SE"
        and g.node("lot:I08-SE")["surveyed_for"] == "Fudgewright"
    )
    deed = {
        "run_id": "r2",
        "agent": "LandBroker",
        "tick": 47000,
        "kind": "land_round",
        "actions": [{"action": "say", "text": "Deed: lot I08-SE is Fudgewright's"}],
        "reasons": ["deeds for surveyed sites paid in full: I08-SE to Fudgewright"],
    }
    assert (
        ingest_record(g, deed) == 4
        and g.promises("LandBroker") == []
        and g.node("lot:I08-SE")["holder"] == "Fudgewright"
    )
    events = [
        {
            "id": 1,
            "tick": 46500,
            "type": "give",
            "actor": "Fudgewright",
            "text": "Fudgewright put 20 wood into the storehouse at (65, 54).",
        },
        {
            "id": 2,
            "tick": 46510,
            "type": "give",
            "actor": "MotherPail",
            "text": "MotherPail gave 3 berries to Tinkerglow.",
        },
        {
            "id": 3,
            "tick": 46520,
            "type": "demolish",
            "actor": "Strayling",
            "text": "Strayling tore down Quill's storehouse at (67, 55) and looted 1 wood.",
        },
        {
            "id": 4,
            "tick": 46530,
            "type": "faction_invited",
            "actor": "Clarion",
            "text": "Clarion invited Quillwright_Ember to Readable Replay.",
        },
    ]
    assert ingest_public_events(g, events) == 4 and ingest_public_events(g, events) == 0
    kinds = g.counts()["edges"]
    assert (
        kinds["deposited"] == 1
        and kinds["gave"] == 1
        and kinds["struck"] == 1
        and kinds["invited"] == 1
    )
    assert (
        g.node("Quill")["kind"] == "agent"
        and g.edges("Quill", kind="struck")[0]["destroyed"] is True
    )
    g.close()


def test_due_jobs_follow_the_knobs_and_the_commands_carry_the_flags():
    personas = load_personas(ROOT)
    crier = personas["town-crier"]
    entry = {"slug": "town-crier", "jobs": ["tick", "shift", "keepalive", "crier"]}
    work_minute = int(crier.knobs["work"]["cron"].split()[0])
    due = due_jobs(crier, datetime(2026, 10, 22, 10, work_minute, tzinfo=UTC), entry)
    assert "shift" in due and "crier" in due and "land" not in due
    assert due_jobs(
        crier, datetime(2026, 10, 22, 10, (work_minute + 33) % 60, tzinfo=UTC), entry
    ) == ["keepalive"]
    assert due_jobs(
        personas["land-broker"],
        datetime(
            2026,
            10,
            22,
            10,
            int(personas["land-broker"].knobs["work"]["cron"].split()[0]),
            tzinfo=UTC,
        ),
        {"slug": "land-broker"},
    ) == ["shift", "land"]
    assert command_for("tick", "town-crier", True)[-3:] == [
        "town-crier",
        "--dry-run",
        "--scheduled",
    ]
    assert "--dry-run" not in command_for("keepalive", "town-crier", True)
    assert command_for("crier", "town-crier", False)[3:5] == ["crier", "round"]


def test_the_supervisor_records_each_job_and_runs_what_is_due(tmp_path):
    calls = []

    def runner(command):
        calls.append(command)
        return 0, "Clarion (bright): work shift: building · 3 action(s)\n"

    config = {
        "dry_run": True,
        "agents": [
            {"slug": "town-crier", "enabled": True, "jobs": ["shift"]},
            {"slug": "wonka", "enabled": False},
        ],
    }
    sup = Supervisor(tmp_path, config, runner)
    record = sup.run_once("town-crier", "shift")
    assert record["exit"] == 0 and record["dry_run"] is True and "work shift" in record["summary"]
    personas = load_personas(ROOT)
    minute = int(personas["town-crier"].knobs["work"]["cron"].split()[0])
    ran = sup.tick(personas, datetime(2026, 10, 22, 11, minute, tzinfo=UTC), wait=True)
    assert ran == [("town-crier", "shift")] and len(calls) == 2
    status = json.loads((tmp_path / "runs/local/status.json").read_text(encoding="utf-8"))
    assert (
        status["agents"]["town-crier"]["last"]["job"] == "shift"
        and len(status["agents"]["town-crier"]["history"]) == 2
    )
    assert (tmp_path / "runs/local/supervisor.log").read_text(encoding="utf-8").count(
        "town-crier shift exit 0"
    ) == 2


def test_agent_cards_and_the_message_endpoint(tmp_path):
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    crier = personas["town-crier"]
    card = agent_card(crier, teams[crier.team], "http://127.0.0.1:8765")
    assert (
        card["protocolVersion"] == "1.0"
        and card["name"] == "Clarion"
        and card["url"].endswith("/agents/town-crier/rpc")
        and card["skills"]
    )
    graph = Graph(tmp_path / "memory.sqlite")
    store = TaskStore(graph)
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(personas, teams, store, "http://127.0.0.1:0", "secret")
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/agents/town-crier/.well-known/agent-card.json"
        ) as resp:
            assert json.loads(resp.read())["name"] == "Clarion"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/agents") as resp:
            assert any(a["slug"] == "wonka" for a in json.loads(resp.read()))
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {"kind": "text", "text": "Clarion, announce the factory survey."}
                        ],
                        "metadata": {"sender": "Warden"},
                    }
                },
            }
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/agents/Clarion/rpc",
            data=body,
            headers={"Content-Type": "application/json", "X-Local-Token": "secret"},
        )
        with urllib.request.urlopen(req) as resp:
            task = json.loads(resp.read())["result"]
        assert task["status"]["state"] == "submitted" and task["metadata"]["sender"] == "Warden"
        assert store.pending_for("Clarion")[0]["id"] == task["id"]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/agents/town-crier/rpc",
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "tasks/cancel", "params": {"id": task["id"]}}
            ).encode(),
            headers={"Content-Type": "application/json", "X-Local-Token": "secret"},
        )
        with urllib.request.urlopen(req) as resp:
            assert json.loads(resp.read())["result"]["status"]["state"] == "canceled"
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/agents/town-crier/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(bad)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        server.shutdown()
        graph.close()


def test_the_status_page_renders_agents_and_configuration(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/local.yaml").write_text(
        "dry_run: true\nagents:\n  - slug: town-crier\n    enabled: true\n", encoding="utf-8"
    )
    html = render(tmp_path, load_personas(ROOT), load_teams(ROOT))
    assert (
        "Clarion" in html
        and 'class="pill dry"' in html
        and 'class="pill actions"' in html
        and "no memory graph yet" in html
        and "Current goal" in html
    )


def test_tasks_reach_the_wake_inbox_and_settle_after_a_live_wake(tmp_path):
    from hglab.local.tasks import deliver, graph_path, settle

    g = Graph(graph_path(tmp_path))
    task = TaskStore(g).create("Clarion", "Warden", "Announce the factory survey at the square.")
    g.close()
    assert deliver("Clarion", tmp_path, 100) == [
        {
            "from": "Warden (operator)",
            "text": "Announce the factory survey at the square.",
            "tick": 100,
            "task": task["id"],
        }
    ]
    g = Graph(graph_path(tmp_path))
    assert (
        TaskStore(g).get(task["id"])["status"]["state"] == "submitted"
    )  # a dry wake changes nothing
    g.close()
    assert settle("Clarion", tmp_path, "r1") == 0
    assert deliver("Clarion", tmp_path, 101, dry_run=False)[0]["task"] == task["id"]
    g = Graph(graph_path(tmp_path))
    assert TaskStore(g).get(task["id"])["status"]["state"] == "working"
    g.close()
    assert settle("Clarion", tmp_path, "r1", dry_run=False) == 1
    assert (
        deliver("Clarion", tmp_path, 102, dry_run=False) == []
        and deliver("Fudgewright", tmp_path, 102) == []
    )
    assert deliver("Clarion", tmp_path / "nowhere", 1) == []  # no graph, no tasks


def test_wakes_carry_the_model_and_its_cost_and_performance_sums_them(tmp_path):
    from hglab.local.memory import ingest_status, wake_attributes

    g = Graph(tmp_path / "memory.sqlite")
    llm = {
        "run_id": "w1",
        "agent": "Clarion",
        "tick": 47000,
        "wake_mode": "act",
        "planner": "llm",
        "author_runtime": "actions-anthropic",
        "dry_run": False,
        "energy_spent": 6,
        "usage": {
            "calls": 1,
            "input_tokens": 900,
            "output_tokens": 120,
            "model": "claude-sonnet-5-5",
            "provider": "anthropic",
            "route": "tick",
        },
        "actions": [{"action": "say", "text": "Hear this!"}, {"action": "move", "x": 1, "y": 2}],
        "failed_actions": [{"action": "move"}],
        "reasons": [],
    }
    plain = {
        "run_id": "w2",
        "agent": "Clarion",
        "tick": 47100,
        "wake_mode": "rest",
        "author_runtime": "local",
        "dry_run": True,
        "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
        "actions": [{"action": "remember", "text": "x"}],
        "reasons": [],
    }
    assert (
        wake_attributes(llm)["model"] == "claude-sonnet-5-5"
        and wake_attributes(plain)["model"] == "heuristic"
    )
    assert ingest_record(g, llm) == 2 and ingest_record(g, plain) == 2
    wake = g.node("wake:w1")
    assert (
        wake["model"] == "claude-sonnet-5-5"
        and wake["actions"] == 2
        and wake["failed"] == 1
        and wake["input_tokens"] == 900
    )
    assert (
        g.node("model:claude-sonnet-5-5")["provider"] == "anthropic"
        and g.edges("Clarion", kind="performed")[0]["model"] == "heuristic"
    )
    status = {
        "agents": {
            "town-crier": {
                "history": [
                    {
                        "job": "tick",
                        "exit": 0,
                        "seconds": 22.3,
                        "dry_run": True,
                        "started_utc": "2026-10-22T15:00:00+00:00",
                        "summary": "dry run",
                    },
                    {
                        "job": "tick",
                        "exit": 1,
                        "seconds": 3.0,
                        "dry_run": True,
                        "started_utc": "2026-10-22T16:00:00+00:00",
                        "summary": "boom",
                    },
                ]
            }
        }
    }
    assert (
        ingest_status(g, status, {"town-crier": "Clarion"}) == 2
        and ingest_status(g, status, {"town-crier": "Clarion"}) == 0
    )
    perf = g.performance("Clarion")
    by_model = {row["model"]: row for row in perf["wakes"]}
    assert (
        by_model["claude-sonnet-5-5"]["wakes"] == 1
        and by_model["claude-sonnet-5-5"]["output_tokens"] == 120
        and by_model["heuristic"]["actions"] == 1
    )
    assert perf["jobs"] == [
        {
            "agent": "Clarion",
            "job": "tick",
            "runs": 2,
            "failures": 1,
            "seconds_per_run": 12.7,
            "last_utc": "2026-10-22T16:00:00+00:00",
        }
    ]
    assert g.performance("Nobody") == {"wakes": [], "jobs": []}
    g.close()


def test_the_stack_is_read_through_a_login_shell_and_started_in_reboot_order(tmp_path):
    from hglab.local import stack

    config = {"nemoclaw": {"sandbox": "hinters", "wsl_distro": "Ubuntu", "ollama": True}}
    prefix = stack.host_shell(config)
    assert prefix[-2:] == ["bash", "-lc"] and (prefix[0] == "wsl") == (
        __import__("platform").system() == "Windows"
    )
    calls = []
    answers = {
        "docker info": (0, "29.2.1"),
        "is-active": (0, "active"),
        "api/tags": (0, "200"),
        "hinters status": (
            0,
            "  Sandbox: hinters\n    Model:    claude-sonnet-5\n    Provider: anthropic-prod\n    OpenClaw: running\n  Phase: Ready\n",
        ),
        "hinters start": (0, "already running"),
        "doctor --fix": (0, "  Summary: healthy with 1 warning(s)"),
    }

    def run(script, timeout=0):
        calls.append(script)
        for key, answer in answers.items():
            if key in script:
                return answer
        return 1, ""

    status = stack.stack_status(config, run)
    assert (
        status["ok"]
        and status["model"] == "claude-sonnet-5"
        and status["phase"] == "Ready"
        and status["ollama"] is True
    )
    said = []
    result = stack.stack_up(config, run, said.append)
    assert (
        result["ok"]
        and any("hinters start" in c for c in calls)
        and any("doctor --fix" in c for c in calls)
    )
    assert said[0].startswith("docker 29.2.1") and "doctor: healthy with 1 warning(s)" in said
    assert stack.stack_status({}, run) == {"configured": False, "sandbox": None}
    answers["api/tags"] = (0, "000")
    said.clear()
    stack.stack_up(config, run, said.append)
    assert any("ollama serve" in c for c in calls) and "ollama not answering on 11434" in said


def test_the_logon_service_renders_for_both_platforms(tmp_path):
    from hglab.local import service

    script = service.render_windows_startup_script(tmp_path, "C:/venv/Scripts/python.exe")
    assert (
        script.startswith("@echo off")
        and "timeout /t 60" in script
        and "-m hglab local up" in script
        and "up.log" in script
    )
    with_auth = service.render_windows_startup_script(
        tmp_path, "C:/venv/Scripts/python.exe", "gcloud"
    )
    assert "-m hglab local up --auth gcloud >>" in with_auth and "--auth" not in script
    unit = service.render_systemd_unit(tmp_path, "/opt/hinters/.venv/bin/python")
    assert (
        "ExecStart=/opt/hinters/.venv/bin/python -m hglab local up" in unit
        and f"WorkingDirectory={tmp_path}" in unit
        and "WantedBy=default.target" in unit
    )


def test_a_failed_job_keeps_the_tail_of_its_output(tmp_path):
    lines = [
        "observing",
        "Traceback (most recent call last):",
        "  File x",
        "ValueError: team square has used its public-speech budget (3/hour)",
    ]

    def runner(command):
        return 1, chr(10).join(lines) + chr(10)

    sup = Supervisor(
        tmp_path, {"dry_run": True, "agents": [{"slug": "town-crier", "jobs": ["tick"]}]}, runner
    )
    record = sup.run_once("town-crier", "tick")
    assert (
        record["exit"] == 1
        and record["tail"][-1].startswith("ValueError")
        and len(record["tail"]) == 4
    )
    assert "  | ValueError" in (tmp_path / "runs/local/supervisor.log").read_text(encoding="utf-8")


def test_a_wake_goes_quiet_instead_of_failing_when_the_team_budget_is_spent():
    from hglab.wake import mute_over_budget

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    crier, square = personas["town-crier"], teams["square"]
    tick = 47000
    events = [
        {"type": "say", "actor": "Clarion", "tick": tick - 100 * n, "text": f"line {n}"}
        for n in range(1, square.social_budget["says_per_hour"] + 1)
    ]
    observe = {"tick": tick, "you": {"name": "Clarion", "id": "x"}, "events": [], "notebook": {}}
    actions = [{"action": "say", "text": "Hear this!"}, {"action": "move", "x": 1, "y": 2}]
    kept, muted = mute_over_budget(actions, crier, square, personas, observe, events, tick)
    assert (
        kept == [{"action": "move", "x": 1, "y": 2}]
        and muted["muted"] == 1
        and "public-speech budget" in muted["why"]
    )
    kept, muted = mute_over_budget(actions, crier, square, personas, observe, [], tick)
    assert kept == actions and muted is None
    assert mute_over_budget(
        [{"action": "move", "x": 1, "y": 2}], crier, square, personas, observe, events, tick
    ) == ([{"action": "move", "x": 1, "y": 2}], None)


def test_capability_cards_carry_roles_tools_performance_and_backups(tmp_path):
    from hglab.local.cards import capability_card, role_charter, write_cards

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    assert role_charter(ROOT, "envoy")["skills"] and role_charter(ROOT, "nobody") == {}
    config = {"a2a_port": 8765, "ecosystem": {"host_id": "host-a", "data_boundary": "internal"}}
    g = Graph(tmp_path / "runs/local/memory.sqlite")
    ingest_record(
        g,
        {
            "run_id": "w9",
            "agent": "Clarion",
            "tick": 47000,
            "wake_mode": "act",
            "usage": {
                "calls": 1,
                "input_tokens": 10,
                "output_tokens": 2,
                "model": "claude-sonnet-5",
                "provider": "anthropic",
            },
            "actions": [{"action": "say", "text": "x"}],
            "reasons": [],
        },
    )
    g.snapshot("first")
    card = capability_card(personas["town-crier"], teams["square"], ROOT, config, g)
    g.close()
    assert card["protocolVersion"] == "1.0" and card["name"] == "Clarion"
    extra = card["x-collective"]
    assert (
        extra["host"] == "host-a"
        and extra["data_boundary"] == "internal"
        and {r["name"] for r in extra["roles"]} == set(personas["town-crier"].roles)
    )
    assert (
        "hg-diplomacy" in extra["skills"]
        and "hinterglass:say" in extra["tools"]
        and "hglab:performance" in extra["tools"]
    )
    assert (
        extra["performance"][0]["model"] == "claude-sonnet-5" and extra["backups"]["snapshots"] == 1
    )
    (tmp_path / "roles").mkdir()
    for role in {r for p in personas.values() for r in p.roles}:
        (tmp_path / "roles" / f"{role}.md").write_text(
            (ROOT / "roles" / f"{role}.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
    paths = write_cards(tmp_path, personas, teams, config)
    assert (
        len(paths) == len(personas)
        and json.loads(paths[0].read_text(encoding="utf-8"))["x-collective"]["performance"] == []
        or True
    )


def test_a_backup_round_trips_through_a_local_target(tmp_path, monkeypatch):
    monkeypatch.setenv("HGLAB_GCP_AUTH", "gcloud")  # this part exercises the gcloud session path
    from hglab.local.backup import list_backups, make_backup, push, restore

    (tmp_path / "config").mkdir()
    (tmp_path / "config/local.yaml").write_text("dry_run: true\nagents: []\n", encoding="utf-8")
    (tmp_path / "runs/local").mkdir(parents=True)
    (tmp_path / "runs/local/status.json").write_text('{"running": false}', encoding="utf-8")
    g = Graph(tmp_path / "runs/local/memory.sqlite")
    g.upsert_node("agent", "Clarion", team="square")
    g.close()
    config = {"ecosystem": {"host_id": "host-a", "backup_target": f"local:{tmp_path / 'offsite'}"}}
    result = push(tmp_path, config)
    assert result["ok"] and result["archive"].endswith(".tar.gz") and "offsite" in result["target"]
    assert list_backups(tmp_path, config)[0]["name"].startswith("host-a-")
    calls = []

    def runner(args):
        calls.append(args)
        return 0, "ok"

    pushed = push(tmp_path, config, "gs://bucket/eco", runner)
    assert (
        pushed["ok"]
        and calls[0][:3] == ["gcloud", "storage", "cp"]
        and calls[0][-1].startswith("gs://bucket/eco/hosts/host-a/backups/")
    )
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    done = restore(fresh, Path(result["archive"]))
    assert (
        "runs/local/memory.sqlite" in done["restored"] and "config/local.yaml" in done["restored"]
    )
    g = Graph(fresh / "runs/local/memory.sqlite")
    assert g.node("Clarion")["team"] == "square"
    g.close()
    again = restore(fresh, Path(result["archive"]))
    assert again["restored"] == [] and "config/local.yaml" in again["skipped"]
    assert make_backup(tmp_path, config).is_file()


def test_the_supervisor_backs_up_on_its_own_schedule(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/local.yaml").write_text("dry_run: true\nagents: []\n", encoding="utf-8")
    pushes = []
    sup = Supervisor(
        tmp_path,
        {
            "dry_run": True,
            "agents": [],
            "ecosystem": {"host_id": "host-a", "backup_every_minutes": 1},
        },
        lambda command: (0, ""),
    )
    sup.backup_runner = lambda root, config: (
        pushes.append(config["ecosystem"]["host_id"])
        or {"ok": True, "target": "gs://bucket/hosts/host-a/backups/x.tar.gz"}
    )
    personas = load_personas(ROOT)
    result = sup.backup(personas)
    assert (
        result["ok"]
        and pushes == ["host-a"]
        and (tmp_path / "runs/local/cards/town-crier.json").is_file()
    )
    status = json.loads((tmp_path / "runs/local/status.json").read_text(encoding="utf-8"))
    assert status["last_backup"]["ok"] is True and status["last_backup"]["target"].startswith(
        "gs://"
    )
    assert "backup ok: gs://bucket" in (tmp_path / "runs/local/supervisor.log").read_text(
        encoding="utf-8"
    )
    sup.backup_runner = lambda root, config: (_ for _ in ()).throw(RuntimeError("no network"))
    assert (
        sup.backup(personas)["ok"] is False
        and json.loads((tmp_path / "runs/local/status.json").read_text(encoding="utf-8"))[
            "last_backup"
        ]["detail"]
        == "no network"
    )


def test_backups_use_the_service_account_client_by_default_and_gcloud_on_request(
    tmp_path, monkeypatch
):
    from hglab.local import backup as bk

    (tmp_path / "config").mkdir()
    (tmp_path / "config/local.yaml").write_text("dry_run: true\nagents: []\n", encoding="utf-8")
    config = {"ecosystem": {"host_id": "host-a", "backup_target": "gs://bucket/eco"}}
    uploads, listed = [], []

    class Blob:
        def __init__(self, name, size=1, updated=None):
            self.name, self.size, self.updated = name, size, updated

        def upload_from_filename(self, path):
            uploads.append((self.name, path))

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        def bucket(self, name):
            listed.append(name)
            return Bucket()

        def list_blobs(self, bucket, prefix=""):
            return [
                Blob(
                    prefix + "host-a-20261022T000000Z.tar.gz", 5, datetime(2026, 10, 22, tzinfo=UTC)
                )
            ]

    monkeypatch.delenv(bk.AUTH_ENV, raising=False)
    assert bk.auth_mode(config) == "service_account"
    result = bk.push(tmp_path, config, client_factory=lambda cfg: Client())
    assert (
        result["ok"]
        and result["auth"] == "service_account"
        and uploads[0][0].startswith("eco/hosts/host-a/backups/")
        and listed == ["bucket"]
    )
    rows = bk.list_backups(tmp_path, config, client_factory=lambda cfg: Client())
    assert rows[0]["name"] == "host-a-20261022T000000Z.tar.gz" and rows[0]["location"].startswith(
        "gs://bucket/eco/hosts/host-a/backups/"
    )
    missing = bk.push(tmp_path, config, client_factory=lambda cfg: None)
    assert missing["ok"] is False and "GCP_HMAC_ACCESS_ID" in missing["detail"]
    calls = []
    monkeypatch.setenv(bk.AUTH_ENV, "gcloud")
    assert bk.auth_mode(config) == "gcloud"
    viagcloud = bk.push(
        tmp_path,
        config,
        runner=lambda args: calls.append(args) or (0, "ok"),
        client_factory=lambda cfg: Client(),
    )
    assert (
        viagcloud["ok"]
        and viagcloud["auth"] == "gcloud"
        and calls[0][:3] == ["gcloud", "storage", "cp"]
    )
    monkeypatch.setenv(bk.AUTH_ENV, "nonsense")
    assert bk.auth_mode(config) == "service_account"


def test_large_secrets_are_chunked_through_the_keyring(monkeypatch):
    from hglab import secrets

    vault = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service, name, value):
            assert len(value) <= 1000
            vault[(service, name)] = value

        @staticmethod
        def get_password(service, name):
            return vault.get((service, name))

    monkeypatch.setattr(secrets.keyring, "set_password", FakeKeyring.set_password)
    monkeypatch.setattr(secrets.keyring, "get_password", FakeKeyring.get_password)
    monkeypatch.delenv("GCP_SERVICE_ACCOUNT_KEY", raising=False)
    big = "{" + "k" * 2300 + "}"
    secrets.store_secret("GCP_SERVICE_ACCOUNT_KEY", big)
    assert (
        vault[("hglab", "GCP_SERVICE_ACCOUNT_KEY")] == "chunked:3"
        and secrets.get_secret("GCP_SERVICE_ACCOUNT_KEY", Path("nowhere")) == big
    )
    secrets.store_secret("OPENAI_API_KEY", "short")
    assert (
        vault[("hglab", "OPENAI_API_KEY")] == "short"
        and secrets.get_secret("OPENAI_API_KEY", Path("nowhere")) == "short"
    )


def test_hmac_requests_are_signed_the_goog4_way():
    from datetime import datetime

    from hglab.local.gcs import ALGORITHM, HmacStorage, client_from_keyring, sign

    when = datetime(2026, 10, 22, 20, 0, 0, tzinfo=UTC)
    url, headers = sign(
        "GOOGACCESS",
        "secret",
        "PUT",
        "my-bucket",
        "hosts/host-a/backups/x.tar.gz",
        None,
        b"payload",
        when,
    )
    assert url == "https://storage.googleapis.com/my-bucket/hosts/host-a/backups/x.tar.gz"
    assert (
        headers["x-goog-date"] == "20261022T200000Z"
        and headers["x-goog-content-sha256"] == __import__("hashlib").sha256(b"payload").hexdigest()
    )
    auth = headers["authorization"]
    assert (
        auth.startswith(
            f"{ALGORITHM} Credential=GOOGACCESS/20261022/auto/storage/goog4_request, SignedHeaders=host;x-goog-content-sha256;x-goog-date, Signature="
        )
        and len(auth.rsplit("=", 1)[1]) == 64
    )
    _same_url, same_headers = sign(
        "GOOGACCESS",
        "secret",
        "PUT",
        "my-bucket",
        "hosts/host-a/backups/x.tar.gz",
        None,
        b"payload",
        when,
    )
    assert same_headers == headers  # deterministic for a fixed time
    _, other = sign(
        "GOOGACCESS",
        "other",
        "PUT",
        "my-bucket",
        "hosts/host-a/backups/x.tar.gz",
        None,
        b"payload",
        when,
    )
    assert other["authorization"] != auth
    listing_url, _ = sign(
        "GOOGACCESS",
        "secret",
        "GET",
        "my-bucket",
        "",
        {"prefix": "hosts/host a/", "list-type": "2"},
        b"",
        when,
    )
    assert (
        listing_url
        == "https://storage.googleapis.com/my-bucket?list-type=2&prefix=hosts%2Fhost%20a%2F"
    )
    assert client_from_keyring(lambda name: None) is None and isinstance(
        client_from_keyring(lambda name: "x"), HmacStorage
    )


def test_a_long_job_never_blocks_another_persona_or_doubles_up(tmp_path):
    import threading
    import time

    gate = threading.Event()
    calls = []

    def runner(command):
        calls.append(command[-3])  # the slug
        if command[-3] == "land-broker":
            gate.wait(5)
        return 0, "done"

    sup = Supervisor(
        tmp_path,
        {
            "dry_run": True,
            "agents": [
                {"slug": "land-broker", "jobs": ["shift"]},
                {"slug": "town-crier", "jobs": ["shift"]},
            ],
        },
        runner,
    )
    personas = load_personas(ROOT)
    minute = int(personas["land-broker"].knobs["work"]["cron"].split()[0])
    when = datetime(2026, 10, 22, 10, minute, tzinfo=UTC)
    started = sup.tick(personas, when)
    assert ("land-broker", "shift") in started
    time.sleep(0.2)
    again = sup.tick(
        personas, when
    )  # the same minute again: LandBroker is busy, so it is skipped, not doubled
    assert ("land-broker", "shift") not in again
    assert "land-broker shift skipped: a job is still running" in (
        tmp_path / "runs/local/supervisor.log"
    ).read_text(encoding="utf-8")
    gate.set()
    sup.tick(personas, when, wait=True)
    assert calls.count("land-broker") == 1 and sup._busy == set()


def test_goals_read_the_newest_record_pick_the_largest_gap_and_brief_once(tmp_path):
    from hglab.local.goals import (
        activity,
        adapt,
        brief,
        key_results,
        latest_record,
        works_and_avoid,
    )

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    day = tmp_path / "runs" / "2026-10-22"
    day.mkdir(parents=True)
    older = {
        "agent": "Clarion",
        "created_utc": "2026-10-22T10:00:00+00:00",
        "summary": "Clarion (bright): resting",
        "approach": "rest",
        "mood": "bright",
        "wake_mode": "rest",
        "results": [{"ok": True}],
        "observe": {"you": {"energy": 100, "inventory": {}}},
        "reasons": [],
    }
    newer = {
        "agent": "Clarion",
        "created_utc": "2026-10-22T12:00:00+00:00",
        "summary": "Clarion (bright): work shift: building the stall",
        "approach": "build",
        "mood": "bright",
        "wake_mode": "act",
        "results": [{"ok": True}, {"ok": False}],
        "observe": {"you": {"energy": 80, "inventory": {"wood": 20, "stone": 5}}},
        "reasons": ["the square needs a stall"],
        "dry_run": False,
    }
    (day / "Clarion-a.json").write_text(json.dumps(older), encoding="utf-8")
    (day / "Clarion-b.json").write_text(json.dumps(newer), encoding="utf-8")
    record = latest_record(tmp_path, "Clarion", "town-crier")
    act = activity(record, "Clarion")
    assert (
        act["summary"] == "work shift: building the stall"
        and act["approach"] == "build"
        and act["ok"] == "1/2"
        and act["pack"] == 25
        and act["energy"] == 80
    )
    for slug in personas:
        (tmp_path / "agents" / slug).mkdir(parents=True, exist_ok=True)
        (tmp_path / "agents" / slug / "metrics.yaml").write_text(
            (ROOT / "agents" / slug / "metrics.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
    krs = key_results(tmp_path, "town-crier")
    assert any(k["id"] == "announced" and k["weight"] == 0.3 for k in krs)
    pulse_dir = tmp_path / "reports" / "agents" / "town-crier"
    pulse_dir.mkdir(parents=True)
    pulse_dir.joinpath("pulse.json").write_text(
        json.dumps(
            {
                "tick": 1,
                "on_mission": {
                    "rows": [
                        {"id": "announced", "progress": 0.9, "value": 18, "target": 20},
                        {"id": "features_found", "progress": 0.1, "value": 1, "target": 6},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    g = Graph(tmp_path / "runs/local/memory.sqlite")
    for n, failed in ((1, 0), (2, 0), (3, 0)):
        ingest_record(
            g,
            {
                "run_id": f"e{n}",
                "agent": "Clarion",
                "tick": 100 + n,
                "approach": "explore",
                "actions": [{"action": "move"}] * 5,
                "failed_actions": [],
                "usage": {},
                "reasons": [],
            },
        )
    for n in range(3):
        ingest_record(
            g,
            {
                "run_id": f"d{n}",
                "agent": "Clarion",
                "tick": 200 + n,
                "approach": "deposit",
                "actions": [{"action": "give"}] * 5,
                "failed_actions": [{"action": "give"}] * 2,
                "usage": {},
                "reasons": [],
            },
        )
    works, avoid = works_and_avoid(
        [
            {"approach": "explore", "wakes": 3, "actions": 15, "failed": 0, "success": 1.0},
            {"approach": "deposit", "wakes": 3, "actions": 15, "failed": 6, "success": 0.6},
            {"approach": "build", "wakes": 1, "actions": 2, "failed": 0, "success": 1.0},
        ]
    )
    assert works == ["explore"] and avoid == ["deposit"]
    plan = adapt(tmp_path, g, personas, teams)
    clarion = plan["agents"]["town-crier"]["assignment"]
    assert (
        clarion["id"] == "features_found"
        and clarion["works"] == ["explore"]
        and clarion["avoid"] == ["deposit"]
        and any("largest weighted gap" in b for b in clarion["because"])
    )
    assert g.edges("Clarion", kind="pursues")[0]["dst"] == "objective:town-crier:features_found"
    assert plan["teams"]["square"]["members"]["town-crier"]["activity"]["approach"] == "build"
    first = brief(tmp_path, g, plan)
    assert "town-crier" in first and brief(tmp_path, g, plan) == []  # once a day
    from hglab.local.a2a import TaskStore

    pending = TaskStore(g).pending_for("Clarion")
    assert pending and "features found" in pending[0]["history"][0]["parts"][0]["text"]
    neverland = plan["teams"]["neverland"]["suggestions"]
    assert any(s["kind"] == "faction" for s in neverland)
    g.close()
