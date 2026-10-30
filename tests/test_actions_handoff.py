"""A host without this one's ledgers (GitHub Actions, 2026-10-30): the world says what stands."""

import base64
import struct
from pathlib import Path

from hglab import factory

ROOT = Path(__file__).resolve().parents[1]


def _packed(blocks, owners):
    data = b"".join(struct.pack("<HHHBBBB", bx, by, owners.index(owner), bz, 1, 0, 0) for bx, by, bz, owner in blocks)
    return {"count": len(blocks), "owners": owners, "data": base64.b64encode(data).decode()}


def test_the_public_blocks_file_decodes_cell_by_cell():
    cells = factory.decode_blocks(_packed([(300, 140, 0, "Fudgewright"), (301, 140, 5, "Plumbline")], ["Fudgewright", "Plumbline"]))
    assert cells == {(300, 140, 0): "Fudgewright", (301, 140, 5): "Plumbline"}


def _standing(steps, upto=None):
    cells = {}
    for step in steps if upto is None else steps[:upto]:
        if step["kind"] == "place":
            cells.update(dict.fromkeys(factory._cells_of(step["action"]), str(step.get("by") or "Fudgewright")))
    return cells


def test_a_host_without_the_ledger_finds_the_factory_standing_and_never_clears_the_new_walls():
    _design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    stores = [{"type": "storehouse", "x": s["action"]["x"], "y": s["action"]["y"]} for s in steps if s["kind"] == "build"]
    assert not factory.design_complete(ROOT, "chocolate-factory")  # an Actions run starts with no ledger
    added = factory.reconcile(ROOT, "chocolate-factory", _standing(steps), stores, tick=118800)
    assert factory.design_complete(ROOT, "chocolate-factory") and len(added) == len(steps)
    clears = [s for s in steps if s["kind"] == "remove"]
    assert clears and all(s["id"] in added for s in clears)  # version 2 stands in the old boxes, so their clears are done
    assert factory.reconcile(ROOT, "chocolate-factory", _standing(steps), stores) == []  # only ever adds


def test_only_what_stands_is_marked_and_a_section_resumes_where_the_world_left_it():
    design, steps, _ = factory.blueprint(ROOT, "lower-manhattan")
    section = steps[0]["section"]
    ours = [s for s in steps if s["section"] == section]
    factory.reconcile(ROOT, "lower-manhattan", _standing(ours, upto=3), [])
    done = set(factory.load_ledger(ROOT, factory.ledger_name(design, "lower-manhattan"))["done"])
    assert {s["id"] for s in ours[:3]} <= done and ours[3]["id"] not in done
    assert factory.ready_steps(steps, done)[0]["id"] == ours[3]["id"]  # the next builder takes the fourth step


def _supervisor(tmp_path):
    from hglab.local.supervisor import Supervisor

    sup = Supervisor(tmp_path, config={"dry_run": False, "agents": []})
    sup._shift_minutes = {"plumbline": 50, "loompa-mason": 40}
    return sup


def test_a_shift_may_run_its_own_length_and_a_timeout_is_reported_not_raised(tmp_path, monkeypatch):
    import subprocess

    sup = _supervisor(tmp_path)
    assert sup._timeout_minutes(["py", "-m", "hglab", "shift", "--agent", "plumbline", "--scheduled"]) == 65  # cut at 40 before (2026-10-30)
    assert sup._timeout_minutes(["py", "-m", "hglab", "shift", "--agent", "loompa-mason", "--scheduled"]) == 55
    assert sup._timeout_minutes(["py", "-m", "hglab", "tick", "--agent", "plumbline", "--scheduled"]) == 40

    def late(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="wake 9 of 10", stderr=None)

    monkeypatch.setattr(subprocess, "run", late)
    code, text = sup._run_subprocess(["py", "-m", "hglab", "shift", "--agent", "plumbline"])
    assert code == 124 and text.startswith("timed out after 65 minutes") and "wake 9 of 10" in text  # text output once raised TypeError


def test_the_heartbeat_sets_the_variable_actions_reads_and_a_clean_stop_clears_it(tmp_path, monkeypatch):
    import subprocess

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
    sup = _supervisor(tmp_path)
    assert sup.heartbeat("2026-10-30T22:00:00+00:00") and sup.heartbeat("")
    assert calls == [["gh", "variable", "set", "HG_LOCAL_HEARTBEAT", "--body", "2026-10-30T22:00:00+00:00"], ["gh", "variable", "set", "HG_LOCAL_HEARTBEAT", "--body", "stopped"]]
