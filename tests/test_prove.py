import yaml

from hglab.prove import prove_claim


def test_claim_proof_reexecutes_analysis_and_compares_output(tmp_path):
    root = tmp_path
    claim = root / "kb/claims/C-20261017-check.md"
    claim.parent.mkdir(parents=True)
    metadata = {
        "id": "C-20261017-check",
        "type": "claim",
        "proof_level": "P2",
        "prove_cmd": "python -c \"print(2)\"",
        "expected": 2,
        "tolerance": 0,
    }
    claim.write_text(f"---\n{yaml.safe_dump(metadata)}---\n", encoding="utf-8")
    assert prove_claim(root, "C-20261017-check")


def test_proof_rejects_unreproducible_claim(tmp_path):
    claim = tmp_path / "kb/claims/C-20261017-check.md"
    claim.parent.mkdir(parents=True)
    claim.write_text("---\nid: C-20261017-check\ntype: claim\nproof_level: P1\n---\n")
    try:
        prove_claim(tmp_path, "C-20261017-check")
    except ValueError as error:
        assert "not a reproducible claim" in str(error)
    else:
        raise AssertionError("P1 claim was executed")
