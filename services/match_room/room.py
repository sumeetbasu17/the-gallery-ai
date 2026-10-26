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
from simulator.scenarios import build_match, fit_outcome, ground_truth, teams_from_scenario
from stats_engine import MatchState

from .store import MatchArchive

log = logging.getLogger("gallery.room")

FRAME_MIN_INTERVAL_S = 0.1   # cap frame broadcasts at 10 per real second
METER_EVERY_MATCH_S = 30.0
HALF_TIME_BREAK_MAX_S = 40.0  # real seconds the replay waits at half-time for the coach reports
HALF_TIME_BREAK_MIN_S = 15.0  # ...and at least this long, so viewers see the break and the reports land
FINISH_TIMEOUT_S = 60.0
KEY_EVENTS = ("goal", "card", "substitution", "half_time", "full_time", "kick_off")
CLIP_MAX_S = 180


def _compact(fr) -> list:
    return [round(fr.second, 1), round(fr.ball.x, 1), round(fr.ball.y, 1),
            [[p.player_id, round(p.x, 1), round(p.y, 1)] for p in fr.players]]


@lru_cache(maxsize=3)
def _regenerate(seed: int, scenario_json: str) -> tuple:
    """Rebuild a match's tracking frames and events from its seed: the simulator is deterministic."""
    scenario = json.loads(scenario_json) if scenario_json else None
    match = build_match(scenario, seed)
    frames = tuple(_compact(env.frame) for env in match.envelopes() if env.kind == "frame")
    return frames, tuple(match.events)


def ball_track(events, start: float, end: float) -> tuple[list, list]:
    """Sub-second ball path and the shots in a window, straight from the events (frames are only 1 Hz).

    A goal finishes inside the net and stays there until the restart, so a replay shows it go in.
    """
    evs = [e for e in events if start - 6 <= e.second <= end + 3]
    keys: list[list[float]] = []
    shots: list[dict] = []
    in_net: list[tuple[float, float]] = []
    for i, e in enumerate(evs):
        if e.start is not None:
            keys.append([e.second, e.start.x, e.start.y])
        if e.end is None or e.type.value not in ("pass", "carry", "shot"):
            continue
        ex, ey = e.end.x, e.end.y
        goal = e.type.value == "shot" and e.outcome == "goal"
        if goal:
            ex = 106.6 if ex > 52.5 else -1.6
        speed = max((e.ball_speed_kmh or 12) / 3.6, 1.0)
        t_end = e.second + ((ex - e.start.x) ** 2 + (ey - e.start.y) ** 2) ** 0.5 / speed if e.start else e.second
        keys.append([round(t_end, 2), round(ex, 2), round(ey, 2)])
        if e.type.value == "shot":
            shots.append({"t": e.second, "t_end": round(t_end, 2), "x0": e.start.x if e.start else ex,
                          "y0": e.start.y if e.start else ey, "x1": round(ex, 2), "y1": round(ey, 2),
                          "outcome": e.outcome, "player_id": e.player_id,
                          "side": e.side.value if e.side else None})
        if goal:
            nxt = next((n.second for n in evs[i + 1:] if n.type.value == "kick_off"), t_end + 30)
            keys.append([round(nxt - 0.05, 2), round(ex, 2), round(ey, 2)])
            in_net.append((round(t_end, 2) + 0.001, nxt - 0.051))
    # the ball stays in the net until the restart, whatever other events are logged meanwhile
    keys = [k for k in keys if not any(a < k[0] < b for a, b in in_net)]
    keys.sort(key=lambda k: k[0])
    return keys, shots


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
        self._report_cache: dict[tuple, dict] = {}

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
            if self.scenario.get("final_score"):
                seed, self.scenario = await asyncio.to_thread(fit_outcome, self.scenario, seed)
                got, want = self.scenario["sim"]["score"], self.scenario["final_score"]
                if (got["home"], got["away"]) != (want["home"], want["away"]):
                    self.scenario["storyline"] += (f" (Closest playable result: {got['home']}-{got['away']}"
                                                   f" instead of {want['home']}-{want['away']}.)")
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

    async def clear(self) -> None:
        """Forget the finished match on screen (after it was deleted from the archive)."""
        if self.status.get("running"):
            return
        self.state = MatchState()
        self.crew = None
        self.trace_log, self.history, self.events_log, self.frames = [], [], [], []
        self.archive_id = None
        self.status = {"running": False, "seed": None, "speed": None, "clock": 0.0, "paused": False,
                       "phase": "idle"}
        await self.broadcast("hello", self.snapshot())

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
        self.crew.match_status = f"over: the producer stopped the match at {minute}'"
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
            "teams": s.team_summary(),
        }

    # ------------------------------------------------------------ replay
    async def replay(self, start: float, end: float, archive_id: Optional[str] = None) -> Optional[list]:
        """Frames for a moment replay: from memory for the live match, regenerated from the seed otherwise."""
        frames = await self._frames_for(archive_id)
        return None if frames is None else clip(frames, start, end)

    async def replay_track(self, start: float, end: float, archive_id: Optional[str] = None) -> tuple[list, list]:
        if not archive_id or archive_id == self.archive_id:
            events = list(self.state.all_events)
        else:
            doc = await self.store.get(archive_id)
            if not doc or doc.get("seed") is None:
                return [], []
            scenario = json.dumps(doc.get("scenario"), sort_keys=True) if doc.get("scenario") else ""
            _, events = await asyncio.to_thread(_regenerate, int(doc["seed"]), scenario)
        return ball_track(events, start, end)

    async def _frames_for(self, archive_id: Optional[str]):
        if not archive_id or archive_id == self.archive_id:
            return self.frames
        doc = await self.store.get(archive_id)
        if not doc or doc.get("seed") is None:
            return None
        scenario = json.dumps(doc.get("scenario"), sort_keys=True) if doc.get("scenario") else ""
        frames, _ = await asyncio.to_thread(_regenerate, int(doc["seed"]), scenario)
        return frames

    async def heatmap(self, player_id: str, archive_id: Optional[str] = None) -> Optional[dict]:
        """Where a player spent the match: share of seconds in each 5 m x 5 m cell (21 x 14 grid)."""
        frames = await self._frames_for(archive_id)
        if frames is None:
            return None
        cols, rows = 21, 14
        grid = [[0] * cols for _ in range(rows)]
        seconds = 0
        for f in frames:
            for pid, x, y in f[3]:
                if pid == player_id:
                    grid[min(rows - 1, int(y / 68 * rows))][min(cols - 1, int(x / 105 * cols))] += 1
                    seconds += 1
                    break
        peak = max((v for row in grid for v in row), default=0) or 1
        return {"player_id": player_id, "cols": cols, "rows": rows, "seconds": seconds,
                "grid": [[round(v / peak, 3) for v in row] for row in grid]}

    @staticmethod
    def zones(frames, player_id: str, attacks_right: bool) -> dict[str, float]:
        """Share of the player's time per third and channel, oriented to their own attacking direction."""
        thirds, channels, n = [0, 0, 0], [0, 0, 0], 0
        for f in frames:
            for pid, x, y in f[3]:
                if pid == player_id:
                    if not attacks_right:
                        x, y = 105 - x, 68 - y
                    thirds[min(2, int(x / 35))] += 1
                    channels[min(2, int(y / (68 / 3)))] += 1
                    n += 1
                    break
        if not n:
            return {}
        pct = lambda v: round(100 * v / n)  # noqa: E731
        return {"defensive_third_pct": pct(thirds[0]), "middle_third_pct": pct(thirds[1]),
                "attacking_third_pct": pct(thirds[2]), "left_channel_pct": pct(channels[0]),
                "central_channel_pct": pct(channels[1]), "right_channel_pct": pct(channels[2]),
                "minutes_on_pitch": round(n / 60)}

    async def player_report(self, player_id: str, archive_id: Optional[str], language: str) -> Optional[dict]:
        from agents.player_report import write_player_report

        live = not archive_id or archive_id == self.archive_id
        if live:
            s = self.state
            if s.meta is None or player_id not in s.players:
                return None
            meta, stats, score, events = s.meta.model_dump(mode="json"), s.player_summary(player_id), s.score, \
                self.events_log
            overlays = [o.model_dump(mode="json") for o in (self.crew.board.overlays if self.crew else [])]
            status = (f"live, minute {s.minute}" if self.status.get("running")
                      else self.crew.match_status if self.crew else "over")
            key = (self.archive_id, player_id, s.minute, language)
        else:
            doc = await self.store.get(archive_id)
            if not doc or player_id not in (doc.get("players") or {}):
                return None
            meta, stats, score, events = doc["metadata"], doc["players"][player_id], doc["score"], doc.get("events", [])
            overlays = doc.get("overlays", [])
            status = ("over: full time" if doc.get("ended") == "full_time"
                      else f"over: stopped by the producer at {doc.get('minute')}'")
            key = (archive_id, player_id, -1, language)
        if key in self._report_cache:
            return self._report_cache[key]
        side = "home" if any(p["id"] == player_id for p in meta["home"]["players"]) else "away"
        frames = await self._frames_for(archive_id)
        name = stats.get("player", "")
        surname = name.split(" ")[-1]
        moments = [f"{o['minute']}' {o['headline']}: {o.get('body') or ''}" for o in overlays
                   if o.get("player_id") == player_id or (o["kind"] in ("tactical_shift", "key_moment")
                                                          and surname and surname in f"{o['headline']} {o.get('body')}")]
        facts = {"status": status, "team": meta[side]["name"],
                 "score": {meta["home"]["name"]: score["home"], meta["away"]["name"]: score["away"]},
                 "stats": stats, "zones": self.zones(frames or [], player_id, side == "home"),
                 "events": [{"type": e["type"], "minute": e["minute"]} for e in events if e.get("player") == name],
                 "moments": moments[-8:]}
        roster = {p["name"] for t in (meta["home"], meta["away"]) for p in t["players"]}
        report = await write_player_report(self.settings, facts, language, roster,
                                           {meta["home"]["name"], meta["away"]["name"]})
        report = {**report, "player_id": player_id, "status": status, "zones": facts["zones"]}
        self._report_cache[key] = report
        return report

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
            if ev.type.value == "full_time" and self.crew:
                self.crew.match_status = "over: full time, the match has finished"
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
        rest = HALF_TIME_BREAK_MIN_S - (time.monotonic() - t0)
        if rest > 0:
            await asyncio.sleep(rest)
        self._pause_total += time.monotonic() - t0
        await self._status(phase="second_half")

    async def _run_local(self, seed: int, speed: float) -> None:
        match = await asyncio.to_thread(build_match, self.scenario, seed)
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
        await publish(seed, speed, scenario, HALF_TIME_BREAK_MIN_S)

    async def _run_eventhub(self, seed: int, speed: float) -> None:
        from .eventhub import consume, publish

        completed = False
        try:
            stream = consume()
            # start the simulator publisher once the consumer is listening
            self._publisher = asyncio.create_task(self._delayed_publish(publish, seed, speed, self.scenario))
            async for env in stream:
                await self.ingest(env)
                # the publisher holds the second half back during the break; mirror it on screen
                if env.kind == "event" and env.event.type.value == "half_time":
                    await self._status(phase="half_time")
                elif env.kind == "frame" and self.status.get("phase") == "half_time" and \
                        env.frame.second > self.status.get("ht_second", 0):
                    await self._status(phase="second_half")
                if env.kind == "event" and env.event.type.value == "half_time":
                    self.status["ht_second"] = env.event.second + 0.5
            completed = True
        finally:
            self.status["running"] = False
            if completed:
                self.status["phase"] = "finishing"
            await self.broadcast("status", self.status)
        if completed:
            await self._finish(ended="full_time")
