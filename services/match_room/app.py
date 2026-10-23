"""HTTP + WebSocket + MCP front door for The Gallery.

    uvicorn match_room.app:app --port 8000          (from the services folder)

Routes
  GET  /api/health                 liveness
  GET  /api/state                  full snapshot (metadata, score, meters, overlays, recap, trace)
  POST /api/match/start            {"seed": 7, "speed": 20, "source": "local" | "eventhub"}
  POST /api/match/stop
  GET  /api/glossary/{term}        Jargon Decoder
  GET  /api/players/{player}       player summary
  WS   /ws                         live stream: frame, meters, overlay, trace, event, recap
  *    /mcp                        MCP server (streamable HTTP) over the live match
  /                                the built web app (web/dist), when present
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import Settings
from mcp_server import create_mcp_server
from mcp_server.glossary import GLOSSARY, lookup

from .room import MatchRoom

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    # Agent Framework emits OpenTelemetry spans for every agent run and tool call;
    # Azure Monitor ships them to Application Insights.
    from azure.monitor.opentelemetry import configure_azure_monitor
    from agent_framework.observability import enable_instrumentation

    configure_azure_monitor(logger_name="gallery")
    enable_instrumentation()

settings = Settings.from_env()
room = MatchRoom(settings)
mcp, _ = create_mcp_server(lambda: room.state)
mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                  host="0.0.0.0")

if os.environ.get("GALLERY_ANALYST_VIA_MCP", "0") == "1":
    from agent_framework import MCPStreamableHTTPTool

    port = os.environ.get("PORT", "8000")
    room.analyst_tools = [MCPStreamableHTTPTool("match", url=f"http://127.0.0.1:{port}/mcp/")]


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        if os.environ.get("GALLERY_AUTOSTART", "0") == "1":
            await room.start(seed=int(os.environ.get("GALLERY_SEED", "7")),
                             speed=float(os.environ.get("GALLERY_SPEED", "20")))
        yield
        await room.stop()


app = FastAPI(title="The Gallery", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/mcp", mcp_app)


class StartRequest(BaseModel):
    seed: int = 7
    speed: float = 20.0
    source: str = "local"


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": settings.mode, "model": settings.fast_model, "running": room.status["running"],
            "eventhub": bool(os.environ.get("EVENTHUB_NAMESPACE")), "cosmos": room.store.enabled}


@app.get("/api/state")
async def state():
    return JSONResponse(room.snapshot())


@app.post("/api/match/start")
async def start(req: StartRequest):
    speed = max(1.0, min(120.0, req.speed))
    await room.start(seed=req.seed, speed=speed, source=req.source)
    return {"started": True, "seed": req.seed, "speed": speed}


@app.post("/api/match/stop")
async def stop():
    await room.stop()
    return {"stopped": True}


@app.get("/api/history")
async def history(limit: int = 50):
    """Insights that aired in recent matches (Cosmos DB), for studio review."""
    return await room.store.recent(limit=max(1, min(200, limit)))


@app.get("/api/glossary")
async def glossary():
    return GLOSSARY


@app.get("/api/glossary/{term}")
async def glossary_term(term: str):
    hit = lookup(term)
    if not hit:
        return JSONResponse({"error": "not found"}, status_code=404)
    metric = hit.get("metric")
    live = None
    if room.state.meta and metric:
        live = _live_metric(metric)
    return {**hit, "live": live}


def _live_metric(metric: str):
    s = room.state
    if metric in ("defensive_line_m", "team_width_m"):
        out = {}
        for side in ("home", "away"):
            rows = list(s.shape[side].samples)[-60:]
            if rows:
                idx = 1 if metric == "defensive_line_m" else 2
                out[s.team_name[side]] = round(sum(r[idx] for r in rows) / len(rows), 1)
        return out
    m = s.meters()
    if metric == "ppda":
        return {k: v["ppda_10min"] for k, v in m["pressure"].items()}
    if metric == "field_tilt_pct":
        return m["control_vs_chaos"]["field_tilt_pct"]
    if metric == "control":
        return {"control": m["control_vs_chaos"]["control"], "label": m["control_vs_chaos"]["label"]}
    if metric == "passes_per_min":
        return {"passes_per_min": m["rhythm"]["passes_per_min"], "label": m["rhythm"]["label"]}
    if metric == "turnovers_per_min":
        return {"turnovers_per_min": m["control_vs_chaos"]["turnovers_per_min"]}
    return None


@app.get("/api/players/{player}")
async def player(player: str):
    if room.crew is None:
        return JSONResponse({"error": "no match running"}, status_code=404)
    return room.crew.match_tools.get_player_summary(player)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await room.join(websocket)
    try:
        while True:
            await websocket.receive_text()  # viewers only listen; pings keep the socket alive
    except WebSocketDisconnect:
        room.leave(websocket)


WEB_DIST = Path(os.environ.get("WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        target = WEB_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
