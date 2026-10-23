import json
from pathlib import Path

from hglab import architecture as arch
from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.persona import load_personas, load_team
from hglab.wake import persona_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def _events():
    rows = []
    tick = 1000
    for kind, x, y in (("hut", 10, 10), ("storehouse", 11, 10), ("farm", 10, 12)):
        tick += 50
        rows.append(
            {
                "id": tick,
                "tick": tick,
                "type": "build",
                "actor": "Marlow",
                "x": x,
                "y": y,
                "text": f"Marlow built a {kind} at ({x}, {y}).",
                "data": {"type": kind},
            }
        )
    for kind, x, y in (("wall", 40, 40), ("wall", 41, 40), ("tower", 42, 41)):
        tick += 50
        rows.append(
            {
                "id": tick,
                "tick": tick,
                "type": "build",
                "actor": "Peregrine",
                "x": x,
                "y": y,
                "text": f"Peregrine built a {kind} at ({x}, {y}).",
                "data": {"type": kind},
            }
        )
    rows.append(
        {
            "id": 9000,
            "tick": 9000,
            "type": "build",
            "actor": "Cairn",
            "x": 70,
            "y": 5,
            "text": "Cairn built a hut at (70, 5).",
            "data": {"type": "hut"},
        }
    )
    rows.append({"id": 9001, "tick": 9001, "type": "say", "actor": "Cairn", "text": "hello"})
    return rows


def test_public_builds_become_sites_patterns_and_recommendations():
    cat = arch.catalogue(_events())
    assert cat["builds"] == 7 and cat["sites"] == 3
    by_sig = {r["signature"]: r for r in cat["patterns"]}
    homestead = by_sig["farm+hut+storehouse"]
    assert homestead["purpose"] == "homestead" and homestead["assembly_order"] == [
        "hut",
        "storehouse",
        "farm",
    ]
    assert (
        homestead["materials"] == {"fiber": 9, "stone": 10, "wood": 35}
        and homestead["builders"] == 1
    )
    compound = by_sig["tower+wall+wall"]
    assert compound["purpose"] == "compound" and compound["materials"] == {"stone": 34, "wood": 10}
    assert "bridge" in cat["blueprints_unseen"] and "hut" in cat["blueprints_seen"]
    storage = arch.recommend(cat, "storage")
    assert (
        storage
        and storage[0]["signature"] == "farm+hut+storehouse"
        and storage[0]["basis"].startswith("stood 1 time")
    )
    crossing = arch.recommend(cat, "crossing")
    assert (
        crossing[0]["signature"] == "bridge"
        and crossing[0]["basis"] == "the rules, untested here"
        and crossing[0]["materials"] == {"wood": 15}
    )
    line = arch.finding_line(homestead)
    assert (
        line.startswith("Workshop note: farm + hut + storehouse for homestead")
        and "Marlow" not in line
        and len(line) <= 240
    )
    sign = arch.sign_text(storage[0])
    assert sign.startswith("Homestead:") and len(sign) <= 200
    assert sorted(
        r["signature"] for r in arch.discoveries({"patterns": [{"signature": "hut"}]}, cat)
    ) == ["farm+hut+storehouse", "tower+wall+wall"]


def test_the_catalogue_round_trips_through_the_file(tmp_path):
    cat = arch.catalogue(_events())
    path = arch.save_catalogue(tmp_path, cat)
    assert path.is_file() and arch.load_catalogue(tmp_path)["sites"] == 3


def _wake(observe, tmp_path):
    personas = load_personas(ROOT)
    persona = personas["plumbline"]
    observe["you"]["name"] = persona.name
    client = FixtureClient(observe)
    lease = acquire(client, persona.name)
    return persona_wake(
        persona=persona,
        team=load_team(ROOT, persona.team),
        personas=personas,
        client=client,
        lease=lease,
        root=ROOT,
        output_dir=tmp_path,
        dry_run=True,
        work=True,
        seed="rnd",
    )


def test_plumbline_announces_a_new_pattern_then_posts_the_recommended_plan_on_a_sign(tmp_path):
    cat = arch.catalogue(_events())
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["energy"] = 100
    observe["you"]["inventory"] = {"wood": 12, "stone": 4, "berries": 2}
    observe["you"]["faction"] = None
    observe["_factions"] = []
    observe["_guidance"] = {
        "architectures": {
            "patterns": cat["patterns"],
            "blueprints_unseen": cat["blueprints_unseen"],
        }
    }
    record = _wake(json.loads(json.dumps(observe)), tmp_path)
    first = next(a for a in record["actions"] if a["action"] != "remember")
    assert (
        first["action"] == "say"
        and first["text"].startswith("Workshop note:")
        and record["approach"] == "research"
    )
    assert "blocks" in record["observe"]
    # with every pattern announced already, the recommended storage plan goes on a sign
    observe["notebook"] = {}
    state = json.loads(
        next(
            a
            for a in record["actions"]
            if a["action"] == "remember" and a.get("key") == "persona_state"
        )["text"]
    )
    state.get("flags", {}).get("arch_announced") or [p["signature"] for p in cat["patterns"]]
    observe["notebook"]["persona_state"] = json.dumps(
        {
            **state,
            "flags": {
                **state.get("flags", {}),
                "arch_announced": [p["signature"] for p in cat["patterns"]],
            },
        }
    )
    second = _wake(json.loads(json.dumps(observe)), tmp_path)
    sign = next(a for a in second["actions"] if a["action"] == "build")
    assert (
        sign["type"] == "sign"
        and sign["text"].startswith("Homestead:")
        and len(sign["text"]) <= 200
    )
