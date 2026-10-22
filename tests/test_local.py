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
    ran = sup.tick(personas, datetime(2026, 10, 22, 11, minute, tzinfo=UTC))
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
        and "runtime: <strong>local</strong>" in html
        and "runtime: <strong>actions</strong>" in html
        and "no memory graph yet" in html
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
