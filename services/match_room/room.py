"""The match room: one live match, its state, its crew and its subscribers.

It ingests envelopes (from the in-process simulator or from Azure Event Hubs),
updates the deterministic stats engine, feeds signals to the agent crew and
broadcasts frames, meters, overlays and agent traces to every connected viewer.

Producer controls: pause / resume (local replay), a real half-time break while the
coach reports are written, and "end match" which stops early and still writes a recap.
Every match is archived when it ends (see store.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from functools import lru_cache
from typing import Any, Optional

from fastapi import WebSocket

from agents import Crew, Settings
from gallery_schema.events import Envelope
from gallery_schema.overlays import Overlay
from simulator import MatchSimulator, northgate_united, riverside_athletic
from simulator.scenarios import ground_truth, teams_from_scenario
from stats_engine import MatchState

from .store import MatchArchive

log = logging.getLogger("gallery.room")

FRAME_MIN_INTERVAL_S = 0.1   # cap frame broadcasts at 10 per real second
METER_EVERY_MATCH_S = 30.0
HALF_TIME_BREAK_MAX_S = 40.0  # real seconds the replay waits at half-time for the coach reports
FINISH_TIMEOUT_S = 60.0
KEY_EVENTS = ("goal", "card", "substitution", "half_time", "full_time", "kick_off")
CLIP_MAX_S = 180


def _compact(fr) -> list:
    return [round(fr.second, 1), round(fr.ball.x, 1), round(fr.ball.y, 1),
            [[p.player_id, round(p.x, 1), round(p.y, 1)] for p in fr.players]]


@lru_cache(maxsize=3)
def _regenerate(seed: int, scenario_json: str) -> tuple:
    """Rebuild a match's tracking frames from its seed: the simulator is deterministic."""
    scenario = json.loads(scenario_json) if scenario_json else None
    home, away = teams_from_scenario(scenario) if scenario else (riverside_athletic(), northgate_united())
    match = MatchSimulator(home, away, seed=seed).run()
    return tuple(_compact(env.frame) for env in match.envelopes() if env.kind == "frame")


def clip(frames, start: float, end: float) -> list:
    start, end = max(0.0, start), min(end, start + CLIP_MAX_S)
    return [f for f in frames if start <= f[0] <= end]


class MatchRoom:
    def __init__(self, settings: Settings, analyst_tools: Optional[list] = None):
        self.settings = settings
        self.analyst_tools = analyst_tools
        self.viewers: set[WebSocket] = set()
        self.state = MatchState()
        self.crew: Optional[Crew] = None
        self.task: Optional[asyncio.Task] = None
        self.status: dict[str, Any] = {"running": False, "seed": None, "speed": None, "clock": 0.0,
                                       "paused": False, "phase": "idle"}
        self.trace_log: list[dict] = []
        self.history: list[dict] = []   # win probability + field tilt over time, for the match story chart
        self.events_log: list[dict] = []
        self.frames: list[list] = []    # compact 1 Hz frames of the live match, for moment replays
        self.scenario: Optional[dict] = None
        self.archive_id: Optional[str] = None
        self.started_at = 0.0
        self.frames_sent = 0
        self._last_frame_sent = 0.0
        self._last_meter = -1e9
        self.store = MatchArchive()
        self._publisher: Optional[asyncio.Task] = None
        self._play = asyncio.Event()
        self._play.set()
        self._paused_at: Optional[float] = None
        self._pause_total = 0.0
        self._finishing: Optional[asyncio.Task] = None

    # ------------------------------------------------------------ viewers
    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.viewers.add(ws)
        await ws.send_text(json.dumps({"type": "hello", "data": self.snapshot()}, default=str, ensure_ascii=False))

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

    async def _status(self, **changes) -> None:
        self.status.update(changes)
        await self.broadcast("status", self.status)

    # ------------------------------------------------------------- state
    def snapshot(self) -> dict[str, Any]:
        s = self.state
        meta = s.meta.model_dump(mode="json") if s.meta else None
        overlays = [o.model_dump(mode="json") for o in (self.crew.board.overlays[-120:] if self.crew else [])]
        return {"status": self.status, "metadata": meta, "score": s.score, "minute": s.minute,
                "teams": s.team_summary() if s.meta else {}, "meters": s.meters() if s.meta else {},
                "overlays": overlays, "recap": self.crew.board.recap if self.crew else None,
                "crew_stats": self.crew.board.stats if self.crew else {}, "trace": self.trace_log[-200:],
                "history": self.history, "coach": self.crew.board.coach_reports if self.crew else {},
                "events": self.events_log, "archive_id": self.archive_id, "languages": self.settings.languages}

    # --------------------------------------------------------------- run
    async def start(self, seed: int = 7, speed: float = 20.0, source: str = "local", brief: str = "") -> None:
        if self._finishing and not self._finishing.done():
            try:  # let the previous match's recap and archive finish first
                await asyncio.wait_for(asyncio.shield(self._finishing), FINISH_TIMEOUT_S)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                self._finishing.cancel()
        if self.task and not self.task.done() and self.status.get("phase") == "finishing":
            try:
                await asyncio.wait_for(asyncio.shield(self.task), FINISH_TIMEOUT_S)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        await self.stop()
        self.scenario = None
        if brief.strip():
            from agents.scenario import write_scenario

            self.scenario = await write_scenario(self.settings, brief)
        self.state = MatchState()
        self.trace_log, self.history, self.events_log, self.frames = [], [], [], []
        self._last_meter = -1e9
        self._play.set()
        self._paused_at, self._pause_total = None, 0.0
        self.started_at = time.time()
        self.archive_id = f"m{int(self.started_at * 1000)}-{seed}"

        async def on_overlay(ov: Overlay) -> None:
            await self.broadcast("overlay", ov.model_dump(mode="json"))

        async def on_trace(step: dict) -> None:
            step = {**step, "minute": self.state.minute, "t": time.time()}
            self.trace_log.append(step)
            await self.broadcast("trace", step)

        async def on_coach(doc: dict) -> None:
            await self.broadcast("coach", doc)

        self.crew = Crew(self.settings, self.state, tools=self.analyst_tools, on_overlay=on_overlay,
                         on_trace=on_trace, on_coach=on_coach)
        self.status = {"running": True, "seed": seed, "speed": speed, "clock": 0.0, "source": source,
                       "paused": False, "phase": "first_half", "can_pause": source == "local",
                       "archive_id": self.archive_id}
        if self.scenario:
            home, away = teams_from_scenario(self.scenario)
            self.status["scenario"] = {"title": self.scenario.get("title"),
                                       "storyline": self.scenario.get("storyline"),
                                       "ground_truth": ground_truth(home, away)}
        runner = self._run_local(seed, speed) if source == "local" else self._run_eventhub(seed, speed)
        self.task = asyncio.create_task(runner)

    async def stop(self) -> None:
        """Cancel the current match without a recap (used before starting a new one)."""
        if self._publisher and not self._publisher.done():
            self._publisher.cancel()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._play.set()
        self.status["running"] = False
        self.status["paused"] = False

    async def pause(self) -> bool:
        if not self.status.get("running") or self.status.get("paused") or not self.status.get("can_pause"):
            return False
        self._play.clear()
        self._paused_at = time.monotonic()
        await self._status(paused=True)
        return True

    async def resume(self) -> bool:
        if not self.status.get("paused"):
            return False
        self._pause_total += time.monotonic() - (self._paused_at or time.monotonic())
        self._paused_at = None
        self._play.set()
        await self._status(paused=False)
        return True

    async def end_early(self) -> bool:
        """The producer ends the match now: stop the feed, write a recap of the match so far, archive it."""
        if not self.status.get("running") or self.crew is None or self.state.meta is None:
            return False
        minute = self.state.minute
        if self._publisher and not self._publisher.done():
            self._publisher.cancel()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._play.set()
        await self._status(running=False, paused=False, phase="finishing")
        self._finishing = asyncio.create_task(self._finish(ended="stopped", stopped_at=minute))
        return True

    async def _finish(self, ended: str, stopped_at: Optional[int] = None) -> None:
        crew = self.crew
        if crew is None:
            return
        crew.board.pending.clear()
        try:
            await asyncio.wait_for(crew.drain(), FINISH_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("crew still busy after %ss; archiving what aired", FINISH_TIMEOUT_S)
        if stopped_at is not None:
            await crew.write_recap(stopped_at=stopped_at)
        if crew.board.recap:
            await self.broadcast("recap", crew.board.recap)
        await self.store.save(self.archive_doc(ended))
        await self._status(running=False, paused=False, phase="ended", ended=ended)

    def archive_doc(self, ended: str) -> dict[str, Any]:
        s, crew = self.state, self.crew
        meta = s.meta
        board = crew.board if crew else None
        overlays = [o.model_dump(mode="json") for o in (board.overlays if board else [])]
        agents: dict[str, dict[str, int]] = {}
        for step in self.trace_log:
            a = agents.setdefault(step["agent"], {"calls": 0, "ms": 0, "errors": 0, "rejected": 0})
            a["calls"] += 1
            a["ms"] += int(step.get("ms") or 0)
            a["errors"] += step.get("status") == "error"
            a["rejected"] += step.get("status") == "rejected"
        recap = board.recap if board else None
        return {
            "id": self.archive_id, "title": f"{meta.home.short_name} {s.score['home']}-{s.score['away']} "
                                            f"{meta.away.short_name}",
            "home": meta.home.name, "away": meta.away.name, "score": s.score, "minute": s.minute, "ended": ended,
            "seed": self.status.get("seed"), "speed": self.status.get("speed"), "source": self.status.get("source"),
            "scenario": self.scenario, "scenario_title": (self.scenario or {}).get("title"),
            "started_at": self.started_at, "ended_at": time.time(),
            "headline": (recap or {}).get("recap", {}).get("headline"),
            "insights": sum(1 for o in overlays if o["kind"] in ("tactical_shift", "key_moment", "match_status")),
            "metadata": meta.model_dump(mode="json"), "overlays": overlays, "recap": recap,
            "coach": board.coach_reports if board else {}, "history": self.history, "events": self.events_log,
            "crew_stats": board.stats if board else {}, "agents": agents, "trace": self.trace_log[-300:],
            "languages": self.settings.languages,
            "players": {pid: s.player_summary(pid) for pid in s.players},
        }

    # ------------------------------------------------------------ replay
    async def replay(self, start: float, end: float, archive_id: Optional[str] = None) -> Optional[list]:
        """Frames for a moment replay: from memory for the live match, regenerated from the seed otherwise."""
        if not archive_id or archive_id == self.archive_id:
            return clip(self.frames, start, end)
        doc = await self.store.get(archive_id)
        if not doc or doc.get("seed") is None:
            return None
        scenario = json.dumps(doc.get("scenario"), sort_keys=True) if doc.get("scenario") else ""
        frames = await asyncio.to_thread(_regenerate, int(doc["seed"]), scenario)
        return clip(frames, start, end)

    # ------------------------------------------------------------ ingest
    async def ingest(self, env: Envelope) -> None:
        signals = self.state.ingest(env)
        if self.crew:
            self.crew.submit(signals)
        if env.kind == "metadata":
            await self.broadcast("metadata", env.metadata.model_dump(mode="json"))
        elif env.kind == "event":
            ev = env.event
            self.status["clock"] = ev.second
            if ev.type.value in KEY_EVENTS:
                doc = {**ev.model_dump(mode="json"), "score": dict(self.state.score),
                       "player": self.state.name(ev.player_id)}
                self.events_log.append(doc)
                await self.broadcast("event", doc)
        elif env.kind == "frame":
            fr = env.frame
            self.status["clock"] = fr.second
            self.frames.append(_compact(fr))
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
                meters = self.state.meters()
                wp = self.crew.match_tools.win_probability() if self.crew else None
                point = None
                if wp and self.state.meta:
                    h, a = self.state.team_name["home"], self.state.team_name["away"]
                    point = {"minute": self.state.minute, "second": fr.second, "home": wp[h], "draw": wp["draw"],
                             "away": wp[a], "tilt_home": meters["control_vs_chaos"]["field_tilt_pct"].get(h, 50),
                             "control": meters["control_vs_chaos"]["control"]}
                    self.history.append(point)
                await self.broadcast("meters", {"minute": self.state.minute, "meters": meters,
                                                "teams": self.state.team_summary(), "win_probability": wp,
                                                "point": point})

    async def _pace(self, t: float, speed: float, started: float) -> None:
        """Wait until match-second t is due, honouring pauses (checked in short slices)."""
        while True:
            await self._play.wait()
            wait = t / max(speed, 0.1) - (time.monotonic() - started - self._pause_total)
            if wait <= 0:
                return
            await asyncio.sleep(min(wait, 0.25))

    async def _half_time_break(self) -> None:
        """Like a real broadcast, hold the second half until both coach reports are ready (bounded)."""
        if self.crew is None:
            return
        await self._status(phase="half_time")
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(self.crew.half_time_done.wait(), HALF_TIME_BREAK_MAX_S)
        except asyncio.TimeoutError:
            log.info("half-time reports still running; restarting play")
        self._pause_total += time.monotonic() - t0
        await self._status(phase="second_half")

    async def _run_local(self, seed: int, speed: float) -> None:
        home, away = teams_from_scenario(self.scenario) if self.scenario else (riverside_athletic(), northgate_united())
        match = await asyncio.to_thread(lambda: MatchSimulator(home, away, seed=seed).run())
        await self.broadcast("status", self.status)
        started = time.monotonic()
        completed = False
        try:
            for env in match.envelopes():
                t = env.event.second if env.event else env.frame.second if env.frame else 0.0
                await self._pace(t, speed, started)
                await self.ingest(env)
                if env.kind == "event" and env.event.type.value == "half_time":
                    await self._half_time_break()
            completed = True
        finally:
            self.status["running"] = False
            if completed:
                self.status["phase"] = "finishing"
            await self.broadcast("status", self.status)
        if completed:
            await self._finish(ended="full_time")

    @staticmethod
    async def _delayed_publish(publish, seed: int, speed: float, scenario) -> None:
        await asyncio.sleep(3)
        await publish(seed, speed, scenario)

    async def _run_eventhub(self, seed: int, speed: float) -> None:
        from .eventhub import consume, publish

        completed = False
        try:
            stream = consume()
            # start the simulator publisher once the consumer is listening
            self._publisher = asyncio.create_task(self._delayed_publish(publish, seed, speed, self.scenario))
            async for env in stream:
                await self.ingest(env)
            completed = True
        finally:
            self.status["running"] = False
            if completed:
                self.status["phase"] = "finishing"
            await self.broadcast("status", self.status)
        if completed:
            await self._finish(ended="full_time")
