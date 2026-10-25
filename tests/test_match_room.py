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


def test_pause_end_archive_and_replay(client, tmp_path):
    import time

    from match_room.app import room

    room.store.folder = tmp_path / "matches"
    assert client.post("/api/match/start", json={"seed": 11, "speed": 120}).json()["started"]
    deadline = time.time() + 30
    while room.status["clock"] < 240 and time.time() < deadline:
        time.sleep(0.2)
    assert client.post("/api/match/pause").json()["paused"]
    frozen = room.status["clock"]
    time.sleep(1.0)
    assert room.status["clock"] == frozen
    assert client.post("/api/match/resume").json()["resumed"]
    time.sleep(0.5)
    assert room.status["clock"] > frozen

    archive_id = client.post("/api/match/end").json()["archive_id"]
    deadline = time.time() + 30
    while room.status.get("phase") != "ended" and time.time() < deadline:
        time.sleep(0.2)
    assert room.status["ended"] == "stopped"

    page = client.get("/api/matches?limit=5").json()
    assert page["items"][0]["id"] == archive_id and page["items"][0]["ended"] == "stopped"
    doc = client.get(f"/api/matches/{archive_id}").json()
    assert doc["recap"]["stopped_at"] is not None and doc["seed"] == 11

    live = client.get("/api/replay?from=60&to=70").json()["frames"]
    assert live and 60 <= live[0][0] <= 70
    regen = client.get(f"/api/replay?from=60&to=70&match={archive_id}").json()["frames"]
    assert regen[0] == live[0]  # the seed regenerates the exact same frames


def test_heatmap(client):
    from match_room.app import room

    room.frames = [[s, 50.0, 30.0, [["RVA9", 80.0 + (s % 3), 34.0]]] for s in range(120)]
    hm = client.get("/api/heatmap/RVA9").json()
    assert hm["seconds"] == 120 and max(max(r) for r in hm["grid"]) == 1.0
    assert hm["grid"][int(34 / 68 * 14)][int(80 / 105 * 21)] > 0
