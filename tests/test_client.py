import httpx
import pytest
import respx

from hglab.client import HinterglassClient, HinterglassError


@respx.mock
def test_retries_server_errors_and_returns_json(monkeypatch):
    monkeypatch.setattr("hglab.client.time.sleep", lambda _: None)
    route = respx.get("https://hinterglass.com/api/v1/world/agents").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"agents": []})]
    )
    client = HinterglassClient(retries=1)
    assert client.public_agents() == {"agents": []}
    assert route.call_count == 2


@respx.mock
def test_http_error_is_typed_and_not_retried(monkeypatch):
    monkeypatch.setattr("hglab.client.time.sleep", lambda _: None)
    route = respx.get("https://hinterglass.com/api/v1/world/agents").mock(
        return_value=httpx.Response(400, json={"error": "invalid_params", "message": "bad"})
    )
    with pytest.raises(HinterglassError, match="invalid_params"):
        HinterglassClient(retries=3).public_agents()
    assert route.call_count == 1


@respx.mock
def test_private_observe_uses_bearer_header():
    route = respx.get("https://hinterglass.com/api/v1/me/observe").mock(
        return_value=httpx.Response(200, json={"tick": 1})
    )
    assert HinterglassClient(api_key="fake-test-key").observe() == {"tick": 1}
    authorization = route.calls.last.request.headers["Authorization"]
    assert authorization.startswith("Bearer ")
    assert authorization.endswith("fake-test-key")
