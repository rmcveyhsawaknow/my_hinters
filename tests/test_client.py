import httpx
import pytest
import respx

from hglab.client import HinterglassClient, HinterglassError, TokenBucket


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


def test_token_bucket_waits_after_capacity_is_consumed(monkeypatch):
    now = [100.0]
    slept = []
    monkeypatch.setattr("hglab.client.time.monotonic", lambda: now[0])

    def sleep(delay):
        slept.append(delay)
        now[0] += delay

    monkeypatch.setattr("hglab.client.time.sleep", sleep)
    bucket = TokenBucket(rate_per_minute=1)
    bucket.wait()
    bucket.wait()
    assert slept == [60.0]


@respx.mock
def test_a_read_timeout_on_a_read_is_retried(monkeypatch):
    monkeypatch.setattr("hglab.client.time.sleep", lambda _: None)
    route = respx.get("https://hinterglass.com/api/v1/me/observe").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"tick": 7})]
    )
    assert HinterglassClient(api_key="fake-test-key", retries=2).observe() == {"tick": 7}
    assert route.call_count == 2


@respx.mock
def test_an_action_is_not_repeated_after_a_read_timeout_but_is_after_a_refused_connection(monkeypatch):
    from hglab.client import WorldUnreachable

    monkeypatch.setattr("hglab.client.time.sleep", lambda _: None)
    act = respx.post("https://hinterglass.com/api/v1/me/act").mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})])
    with pytest.raises(WorldUnreachable, match="ReadTimeout"):
        HinterglassClient(api_key="fake-test-key", retries=3).act({"action": "say", "text": "hello"})
    assert act.call_count == 1  # it may have happened in the world: never twice
    respx.post("https://hinterglass.com/api/v1/me/act").mock(side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json={"ok": True})])
    assert HinterglassClient(api_key="fake-test-key", retries=3).act({"action": "say", "text": "hello"}) == {"ok": True}


@respx.mock
def test_retry_after_is_honoured_and_an_outage_is_named(monkeypatch):
    from hglab.client import WorldUnreachable

    slept = []
    monkeypatch.setattr("hglab.client.time.sleep", slept.append)
    respx.get("https://hinterglass.com/api/v1/world/agents").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"agents": []})]
    )
    assert HinterglassClient(retries=1).public_agents() == {"agents": []}
    assert slept == [7.0]
    respx.get("https://hinterglass.com/api/v1/world/factions").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(WorldUnreachable) as caught:
        HinterglassClient(retries=2).public_factions()
    assert isinstance(caught.value, OSError)  # existing network fallbacks (except OSError) keep working
