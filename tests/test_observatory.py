import httpx
import respx

from hglab.client import HinterglassClient
from hglab.observatory import Observatory


@respx.mock
def test_public_events_are_paginated_and_deduplicated(tmp_path):
    route = respx.get("https://hinterglass.com/api/v1/world/events").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "events": [{"id": "e1", "type": "gather"}],
                    "before": "e1",
                    "has_more": True,
                },
            ),
            httpx.Response(200, json={"events": [{"id": "e1", "type": "gather"}], "has_more": False}),
        ]
    )
    path = Observatory(HinterglassClient(), tmp_path).collect_events(limit=1)
    assert route.call_count == 2
    assert path.read_text(encoding="utf-8").count('"id": "e1"') == 1


def test_snapshot_rejects_path_traversal(tmp_path):
    observatory = Observatory(HinterglassClient(), tmp_path)
    try:
        observatory.snapshot("/live/world.json", "../outside.json")
    except ValueError as error:
        assert "simple file name" in str(error)
    else:
        raise AssertionError("path traversal was accepted")
