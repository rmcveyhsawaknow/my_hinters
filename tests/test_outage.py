import typer
from typer.testing import CliRunner

from hglab.client import WorldUnreachable
from hglab.outage import tolerate_outage

app = typer.Typer()


@app.command()
@tolerate_outage
def wake(agent: str = typer.Option(..., "--agent")) -> None:
    raise WorldUnreachable(f"GET /api/v1/me/observe: ReadTimeout after 4 attempt(s) for {agent}")


def test_an_outage_warns_and_passes_under_actions(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    result = CliRunner().invoke(app, ["--agent", "Clarion"])
    assert result.exit_code == 0
    assert "::warning title=Hinterglass unreachable::" in result.output
    assert "Hinterglass unreachable" in summary.read_text(encoding="utf-8")


def test_an_outage_fails_outside_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = CliRunner().invoke(app, ["--agent", "Clarion"])
    assert result.exit_code == 1
