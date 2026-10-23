"""Match room API smoke tests (offline mode)."""

import os

os.environ["GALLERY_MODE"] = "offline"

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from match_room.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # the MCP session manager may only start once per process
        yield c


def test_health_glossary_and_mcp(client):
    assert client.get("/api/health").json()["mode"] == "offline"
    g = client.get("/api/glossary/low block").json()
    assert "definition" in g and g["metric"] == "defensive_line_m"
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"accept": "application/json, text/event-stream"})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"get_team_shape", "win_probability", "explain_term"} <= names


def test_websocket_hello(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "hello" and "status" in msg["data"]
