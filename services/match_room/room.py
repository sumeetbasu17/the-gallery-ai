"""The match room: one live match, its state, its crew and its subscribers.

It ingests envelopes (from the in-process simulator or from Azure Event Hubs),
updates the deterministic stats engine, feeds signals to the agent crew and
broadcasts frames, meters, overlays and agent traces to every connected viewer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from fastapi import WebSocket

from agents import Crew, Settings
from gallery_schema.events import Envelope
from gallery_schema.overlays import Overlay
from simulator import MatchSimulator, northgate_united, riverside_athletic
from stats_engine import MatchState

from .store import InsightStore

log = logging.getLogger("gallery.room")

FRAME_MIN_INTERVAL_S = 0.1   # cap frame broadcasts at 10 per real second
METER_EVERY_MATCH_S = 30.0


class MatchRoom:
    def __init__(self, settings: Settings, analyst_tools: Optional[list] = None):
        self.settings = settings
        self.analyst_tools = analyst_tools
        self.viewers: set[WebSocket] = set()
        self.state = MatchState()
        self.crew: Optional[Crew] = None
        self.task: Optional[asyncio.Task] = None
        self.status: dict[str, Any] = {"running": False, "seed": None, "speed": None, "clock": 0.0}
        self.trace_log: list[dict] = []
        self.frames_sent = 0
        self._last_frame_sent = 0.0
        self._last_meter = -1e9
        self.store = InsightStore()
        self._publisher: Optional[asyncio.Task] = None

    # ------------------------------------------------------------ viewers
    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.viewers.add(ws)
        await ws.send_text(json.dumps({"type": "hello", "data": self.snapshot()}, default=str))

    def leave(self, ws: WebSocket) -> None:
        self.viewers.discard(ws)

    async def broadcast(self, kind: str, data: Any) -> None:
        if not self.viewers:
            return
        msg = json.dumps({"type": kind, "data": data}, default=str, ensure_ascii=False)
        dead = []
        for ws in list(self.viewers):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.viewers.discard(ws)

    # ------------------------------------------------------------- state
    def snapshot(self) -> dict[str, Any]:
        s = self.state
        meta = s.meta.model_dump(mode="json") if s.meta else None
        overlays = [o.model_dump(mode="json") for o in (self.crew.board.overlays[-40:] if self.crew else [])]
        return {"status": self.status, "metadata": meta, "score": s.score, "minute": s.minute,
                "teams": s.team_summary() if s.meta else {}, "meters": s.meters() if s.meta else {},
                "overlays": overlays, "recap": self.crew.board.recap if self.crew else None,
                "crew_stats": self.crew.board.stats if self.crew else {}, "trace": self.trace_log[-60:],
                "languages": self.settings.languages}

    # --------------------------------------------------------------- run
    async def start(self, seed: int = 7, speed: float = 20.0, source: str = "local") -> None:
        await self.stop()
        self.state = MatchState()
        self.trace_log = []
        self._last_meter = -1e9

        async def on_overlay(ov: Overlay) -> None:
            doc = ov.model_dump(mode="json")
            await self.broadcast("overlay", doc)
            if ov.kind.value in ("tactical_shift", "key_moment", "match_status"):
                await self.store.save({**doc, "id": ov.overlay_id, "saved_at": time.time()})
            if self.crew and self.crew.board.recap and ov.kind.value == "match_status" and ov.minute >= 90:
                await self.broadcast("recap", self.crew.board.recap)

        async def on_trace(step: dict) -> None:
            step = {**step, "minute": self.state.minute, "t": time.time()}
            self.trace_log.append(step)
            await self.broadcast("trace", step)

        self.crew = Crew(self.settings, self.state, tools=self.analyst_tools, on_overlay=on_overlay,
                         on_trace=on_trace)
        self.status = {"running": True, "seed": seed, "speed": speed, "clock": 0.0, "source": source}
        runner = self._run_local(seed, speed) if source == "local" else self._run_eventhub(seed, speed)
        self.task = asyncio.create_task(runner)

    async def stop(self) -> None:
        if self._publisher and not self._publisher.done():
            self._publisher.cancel()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.status["running"] = False

    async def ingest(self, env: Envelope) -> None:
        signals = self.state.ingest(env)
        if self.crew:
            self.crew.submit(signals)
        if env.kind == "metadata":
            await self.broadcast("metadata", env.metadata.model_dump(mode="json"))
        elif env.kind == "event":
            ev = env.event
            self.status["clock"] = ev.second
            if ev.type.value in ("goal", "card", "substitution", "half_time", "full_time", "kick_off"):
                await self.broadcast("event", {**ev.model_dump(mode="json"), "score": self.state.score,
                                               "player": self.state.name(ev.player_id)})
        elif env.kind == "frame":
            fr = env.frame
            self.status["clock"] = fr.second
            if self.crew:
                self.crew.tick(fr.second)
            now = time.monotonic()
            if now - self._last_frame_sent >= FRAME_MIN_INTERVAL_S:
                self._last_frame_sent = now
                self.frames_sent += 1
                await self.broadcast("frame", {"second": fr.second, "minute": self.state.minute,
                                               "ball": [fr.ball.x, fr.ball.y],
                                               "players": [[p.player_id, p.x, p.y, p.speed_kmh]
                                                           for p in fr.players],
                                               "score": self.state.score})
            if fr.second - self._last_meter >= METER_EVERY_MATCH_S:
                self._last_meter = fr.second
                await self.broadcast("meters", {"minute": self.state.minute, "meters": self.state.meters(),
                                                "teams": self.state.team_summary(),
                                                "win_probability": self.crew.match_tools.win_probability()
                                                if self.crew else None})

    async def _run_local(self, seed: int, speed: float) -> None:
        match = MatchSimulator(riverside_athletic(), northgate_united(), seed=seed).run()
        started = time.monotonic()
        try:
            for env in match.envelopes():
                t = env.event.second if env.event else env.frame.second if env.frame else 0.0
                wait = t / max(speed, 0.1) - (time.monotonic() - started)
                if wait > 0:
                    await asyncio.sleep(wait)
                await self.ingest(env)
            if self.crew:
                await self.crew.drain()
                if self.crew.board.recap:
                    await self.broadcast("recap", self.crew.board.recap)
                    await self.store.save({"id": f"recap-{match.metadata.match_id}",
                                           "match_id": match.metadata.match_id, "kind": "recap",
                                           "saved_at": time.time(), **self.crew.board.recap})
        finally:
            self.status["running"] = False
            await self.broadcast("status", self.status)

    @staticmethod
    async def _delayed_publish(publish, seed: int, speed: float) -> None:
        await asyncio.sleep(3)
        await publish(seed, speed)

    async def _run_eventhub(self, seed: int, speed: float) -> None:
        from .eventhub import consume, publish

        try:
            stream = consume()
            # start the simulator publisher once the consumer is listening
            self._publisher = asyncio.create_task(self._delayed_publish(publish, seed, speed))
            async for env in stream:
                await self.ingest(env)
            if self.crew:
                await self.crew.drain()
                if self.crew.board.recap:
                    await self.broadcast("recap", self.crew.board.recap)
                    await self.store.save({"id": f"recap-{self.state.meta.match_id}",
                                           "match_id": self.state.meta.match_id, "kind": "recap",
                                           "saved_at": time.time(), **self.crew.board.recap})
        finally:
            self.status["running"] = False
            await self.broadcast("status", self.status)
