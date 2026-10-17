from hglab.secrets import get_api_key, secret_name


def test_secret_name_normalizes_dash_and_rejects_invalid_chars():
    assert secret_name("Agent-1") == "HG_KEY_AGENT_1"
    try:
        secret_name("bad.name")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid secret name accepted")


def test_environment_key_precedes_dotenv_fallback(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("HG_KEY_AGENT=dotenv-value\n", encoding="utf-8")
    monkeypatch.setenv("HG_KEY_AGENT", "environment-value")
    assert get_api_key("agent", tmp_path) == "environment-value"


def test_dotenv_is_used_when_environment_is_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("HG_KEY_AGENT", raising=False)
    (tmp_path / ".env").write_text("HG_KEY_AGENT=dotenv-value\n", encoding="utf-8")
    assert get_api_key("agent", tmp_path) == "dotenv-value"
