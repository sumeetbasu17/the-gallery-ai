"""HTTP + WebSocket + MCP front door for The Gallery.

    uvicorn match_room.app:app --port 8000          (from the services folder)

Routes
  GET  /api/health                 liveness
  GET  /api/state                  full snapshot (metadata, score, meters, overlays, recap, trace)
  POST /api/match/start            {"seed": 7, "speed": 20, "source": "local" | "eventhub"}
  POST /api/match/stop             cancel without a recap
  POST /api/match/pause | resume   producer controls (local replay)
  POST /api/match/end              end early: recap of the match so far, then archive
  GET  /api/matches?limit&cursor   archived matches, newest first (paginated)
  GET  /api/matches/{id}           one archived match (overlays, recap, coach reports, chart)
  GET  /api/replay?from&to&match   tracking frames for a moment replay (regenerated from the seed)
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

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import Settings
from mcp_server import create_mcp_server
from mcp_server.glossary import GLOSSARY, lookup

from .room import MatchRoom
from .speech import available as speech_available

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
    brief: str = ""


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": settings.mode, "model": settings.fast_model, "running": room.status["running"],
            "eventhub": bool(os.environ.get("EVENTHUB_NAMESPACE")), "archive": room.store.backend,
            "speech": speech_available()}


@app.get("/api/state")
async def state():
    return JSONResponse(room.snapshot())


@app.post("/api/match/start")
async def start(req: StartRequest):
    speed = max(1.0, min(120.0, req.speed))
    await room.start(seed=req.seed, speed=speed, source=req.source, brief=req.brief)
    return {"started": True, "seed": req.seed, "speed": speed, "scenario": room.status.get("scenario")}


@app.post("/api/match/stop")
async def stop():
    await room.stop()
    return {"stopped": True}


@app.post("/api/match/pause")
async def pause():
    return {"paused": await room.pause()}


@app.post("/api/match/resume")
async def resume():
    return {"resumed": await room.resume()}


@app.post("/api/match/end")
async def end_match():
    ok = await room.end_early()
    if not ok:
        return JSONResponse({"error": "No match is running."}, status_code=409)
    return {"ending": True, "archive_id": room.archive_id}


@app.get("/api/matches")
async def matches(limit: int = 10, cursor: str = ""):
    return await room.store.list(limit=limit, cursor=cursor or None)


@app.get("/api/matches/{match_id}")
async def match_detail(match_id: str):
    doc = await room.store.get(match_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)
    return doc


@app.delete("/api/matches/{match_id}")
async def match_delete(match_id: str):
    return {"deleted": await room.store.delete(match_id)}


@app.get("/api/replay")
async def replay(start: float = Query(alias="from"), end: float = Query(alias="to"), match: str = ""):
    frames = await room.replay(start, end, match or None)
    if frames is None:
        return JSONResponse({"error": "This match can't be replayed."}, status_code=404)
    return {"frames": frames}


class AskRequest(BaseModel):
    question: str
    language: str = "en"


@app.post("/api/ask")
async def ask(req: AskRequest):
    """Ask the pundit: a viewer question answered live from the match tools, fact-checked."""
    if room.crew is None or room.state.meta is None:
        return JSONResponse({"error": "Kick off a match first."}, status_code=409)
    lang = req.language if req.language in settings.languages else "en"
    return await room.crew.ask(req.question, lang)


@app.post("/api/coach/{side}")
async def coach(side: str):
    """Coach report for one club ('home' or 'away'), on demand."""
    if side not in ("home", "away"):
        return JSONResponse({"error": "side must be home or away"}, status_code=400)
    if room.crew is None or room.state.meta is None:
        return JSONResponse({"error": "Kick off a match first."}, status_code=409)
    return await room.crew.coach_report(side)


class SpeechRequest(BaseModel):
    text: str
    language: str = "en"


@app.post("/api/speech")
async def speech(req: SpeechRequest):
    """Natural-voice audio via Azure AI Speech (keyless). 204 means: use the browser voice instead."""
    from fastapi import Response

    from .speech import synthesize

    audio = await synthesize(req.text[:3000], req.language)
    if audio is None:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/mpeg")




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
