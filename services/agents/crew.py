"""The Gallery crew: specialised agents that turn signals into verified, personalised overlays.

Flow for one narrative moment
-----------------------------
    stats engine Signal
      -> Match Director        decides whether/when it airs (budget, cooldowns, LLM tie-break)
      -> Tactical Analyst  ||  Moment Judge          (parallel; Analyst investigates via MCP tools)
      -> Storyteller           writes the line from FACTS + analyst note + verdict
      -> Fact-Checker          deterministic numbers/names/direction check (+ LLM semantic check)
           rejected? -> Storyteller rewrites with feedback (once) -> template fallback
      -> Fan Producer          casual / analyst / home / away versions, per language (parallel)
      -> Overlay               timed, machine-readable, with evidence and the full agent trace

Quick signals (sprints, shot speed, pass difficulty, cards, subs) become data tags with no LLM call:
graphics that need no words should not spend tokens.

Everything shared lives on the blackboard (`Board`): aired moments, cooldowns, win-probability history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from agent_framework import Agent

from gallery_schema.overlays import AgentStep, Overlay, OverlayKind, Variant
from mcp_server import MatchTools
from mcp_server.glossary import find_terms, lookup
from stats_engine import MatchState, Signal, SignalType

from . import fallback, prompts
from .config import Settings, make_client
from .contracts import (
    AnalystNote,
    CoachReport,
    DirectorPlan,
    FanVersions,
    JudgeVerdict,
    PunditAnswer,
    Recap,
    RecapTranslation,
    SemanticCheck,
    Story,
)
from .factcheck import allowed_numbers, check_story

log = logging.getLogger("gallery.crew")

MANDATORY = {SignalType.GOAL, SignalType.HALF_TIME, SignalType.FULL_TIME}
TACTICAL = {SignalType.BLOCK_SHIFT, SignalType.WIDTH_SHIFT, SignalType.PRESS_SHIFT, SignalType.MOMENTUM_SWING}
KEY = {SignalType.GOAL, SignalType.BIG_CHANCE}
QUICK = {SignalType.SPRINT, SignalType.POWER_SHOT, SignalType.ELITE_PASS, SignalType.PASS_STREAK,
         SignalType.CARD, SignalType.SUBSTITUTION}

KIND = {
    SignalType.GOAL: OverlayKind.KEY_MOMENT, SignalType.BIG_CHANCE: OverlayKind.KEY_MOMENT,
    SignalType.BLOCK_SHIFT: OverlayKind.TACTICAL_SHIFT, SignalType.WIDTH_SHIFT: OverlayKind.TACTICAL_SHIFT,
    SignalType.PRESS_SHIFT: OverlayKind.TACTICAL_SHIFT, SignalType.MOMENTUM_SWING: OverlayKind.TACTICAL_SHIFT,
    SignalType.SPRINT: OverlayKind.PLAYER_TAG, SignalType.POWER_SHOT: OverlayKind.SHOT_SPEED,
    SignalType.ELITE_PASS: OverlayKind.PASS_QUALITY, SignalType.PASS_STREAK: OverlayKind.MILESTONE,
    SignalType.CARD: OverlayKind.KEY_MOMENT, SignalType.SUBSTITUTION: OverlayKind.MILESTONE,
    SignalType.HALF_TIME: OverlayKind.MATCH_STATUS, SignalType.FULL_TIME: OverlayKind.MATCH_STATUS,
}

QUICK_LABELS = {
    "en": {"sprint": "Top speed", "power_shot": "Shot speed", "elite_pass": "Pass difficulty",
           "pass_streak": "passes in a row", "card": "Yellow card", "substitution": "Substitution"},
    "hi": {"sprint": "टॉप स्पीड", "power_shot": "शॉट की रफ़्तार", "elite_pass": "पास की कठिनाई",
           "pass_streak": "लगातार पास", "card": "पीला कार्ड", "substitution": "खिलाड़ी बदला"},
    "es": {"sprint": "Velocidad máxima", "power_shot": "Velocidad del disparo", "elite_pass": "Dificultad del pase",
           "pass_streak": "pases seguidos", "card": "Tarjeta amarilla", "substitution": "Cambio"},
}

AIR_BUDGET_PER_5_MIN = 3
TACTICAL_COOLDOWN_S = 120.0
DIRECTOR_HOLD_S = 45.0  # match-seconds a candidate waits so the Director can compare it with others


@dataclass
class Board:
    """Shared state for the whole crew."""

    aired: list[dict] = field(default_factory=list)          # {minute, type, headline, second}
    pending: list[Signal] = field(default_factory=list)
    last_air_by_type: dict[str, float] = field(default_factory=dict)
    win_prob: list[dict] = field(default_factory=list)
    coach_reports: dict[str, dict] = field(default_factory=dict)  # side -> report
    overlays: list[Overlay] = field(default_factory=list)
    recap: Optional[dict] = None
    stats: dict[str, int] = field(default_factory=lambda: {"llm_calls": 0, "rejections": 0, "fallbacks": 0,
                                                           "errors": 0})

    def aired_recently(self, now: float, window: float = 300.0) -> int:
        return sum(1 for a in self.aired if now - a["second"] <= window and a["type"] not in
                   {t.value for t in MANDATORY})


def _unlabel(text: str, teams: set[str]) -> str:
    """Drop a leading 'Riverside Athletic fans:' style label from a club-voice line."""
    head, sep, rest = (text or "").partition(":")
    if sep and len(head) <= 50 and rest.strip() and any(t.split()[0].lower() in head.lower() for t in teams if t):
        return rest.strip()[:1].upper() + rest.strip()[1:]
    return text


def glossary_terms(suggested: list[str], text: str, limit: int = 3) -> list[str]:
    """Only terms the Jargon Decoder can actually explain, de-duplicated, at most `limit`."""
    out: list[str] = []
    for t in [*suggested, *find_terms(text)]:
        hit = lookup(t)
        if hit and hit["term"] not in out:
            out.append(hit["term"])
    return out[:limit]


class Crew:
    def __init__(self, settings: Settings, state: MatchState, tools: Optional[list] = None,
                 client_factory: Optional[Callable[[str], Any]] = None,
                 on_overlay: Optional[Callable[[Overlay], Awaitable[None] | None]] = None,
                 on_trace: Optional[Callable[[dict], Awaitable[None] | None]] = None,
                 on_coach: Optional[Callable[[dict], Awaitable[None] | None]] = None):
        self.settings = settings
        self.state = state
        self.board = Board()
        self.match_tools = MatchTools(lambda: self.state)
        self.tools = tools if tools is not None else self.match_tools.all()
        self.on_overlay = on_overlay
        self.on_trace = on_trace
        self.on_coach = on_coach
        factory = client_factory or (lambda model: make_client(settings, model))
        fast, creative = factory(settings.fast_model), factory(settings.creative_model)
        self.director = Agent(fast, prompts.DIRECTOR, name="match_director")
        self.analyst = Agent(fast, prompts.ANALYST, name="tactical_analyst", tools=self.tools)
        self.judge = Agent(fast, prompts.JUDGE, name="moment_judge", tools=[self.match_tools.win_probability])
        self.storyteller = Agent(creative, prompts.STORYTELLER, name="storyteller")
        self.factchecker = Agent(fast, prompts.FACT_CHECKER, name="fact_checker")
        self.fan_producer = Agent(fast, prompts.FAN_PRODUCER, name="fan_producer")
        self.recap_writer = Agent(creative, prompts.RECAP, name="recap_writer")
        self.pundit = Agent(fast, prompts.PUNDIT, name="pundit", tools=self.tools)
        self.coach = Agent(creative, prompts.COACH, name="coach", tools=self.tools)
        self.translator = Agent(fast, prompts.TRANSLATOR, name="translator")
        self._sem = asyncio.Semaphore(settings.max_parallel_moments)
        self._facts: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task] = set()
        self.half_time_done = asyncio.Event()  # both half-time coach reports written

    # ------------------------------------------------------------------ utils
    async def _emit(self, cb, payload) -> None:
        if cb is None:
            return
        res = cb(payload)
        if asyncio.iscoroutine(res):
            await res

    async def _call(self, agent: Agent, payload: dict, fmt, trace: list[AgentStep], action: str,
                    tools: Optional[list] = None):
        """Run one agent with a timeout; record the hop. Returns (value, tool_results) or (None, [])."""
        t0 = time.perf_counter()
        self.board.stats["llm_calls"] += 1
        try:
            kwargs: dict[str, Any] = {"options": {"response_format": fmt}}
            if tools is not None:
                kwargs["tools"] = tools
            resp = await asyncio.wait_for(agent.run(json.dumps(payload, ensure_ascii=False, default=str), **kwargs),
                                          timeout=self.settings.llm_timeout_s)
            value = resp.value
            if value is None and resp.text:
                value = fmt.model_validate_json(resp.text)
            tool_results = [c.result for m in (resp.messages or []) for c in m.contents
                            if c.type == "function_result"]
            ms = int((time.perf_counter() - t0) * 1000)
            note = f"{len(tool_results)} tool call(s)" if tool_results else None
            trace.append(AgentStep(agent=agent.name, action=action, ms=ms, note=note))
            await self._emit(self.on_trace, {"agent": agent.name, "action": action, "status": "ok", "ms": ms})
            return value, tool_results
        except Exception as exc:  # noqa: BLE001 - any model/tool failure must degrade gracefully
            ms = int((time.perf_counter() - t0) * 1000)
            self.board.stats["errors"] += 1
            log.warning("%s failed: %s", agent.name, exc)
            trace.append(AgentStep(agent=agent.name, action=action, status="error", ms=ms,
                                   note=type(exc).__name__))
            await self._emit(self.on_trace, {"agent": agent.name, "action": action, "status": "error", "ms": ms})
            return None, []

    async def _step(self, trace: list[AgentStep], agent: str, action: str, status: str = "ok",
                    note: Optional[str] = None) -> None:
        trace.append(AgentStep(agent=agent, action=action, status=status, note=note))
        await self._emit(self.on_trace, {"agent": agent, "action": action, "status": status, "ms": 0,
                                         "note": note})

    def roster(self) -> set[str]:
        return set(self.state.names.values())

    def fact_sheet(self, signal: Signal) -> dict[str, Any]:
        """Deterministic facts for this moment. Storyteller and Fact-Checker both work from these."""
        t = self.match_tools
        facts: dict[str, Any] = {"minute": signal.minute, "snapshot": t.get_match_snapshot(),
                                 "win_probability": t.win_probability(), "meters": t.get_meters(5)}
        if signal.side:
            facts["team_shape"] = t.get_team_shape(signal.side)
        if signal.player_id:
            facts["player"] = self.state.player_summary(signal.player_id)
        return facts

    # --------------------------------------------------------------- intake
    def submit(self, signals: list[Signal]) -> None:
        """Called by the match room as soon as the stats engine produces signals.

        The fact sheet is frozen here, at the moment of the signal, so a story written a few seconds
        later still describes the match as it was when the moment happened.
        """
        for s in signals:
            if s.type not in QUICK:
                self._facts[s.signal_id] = self.fact_sheet(s)
            if s.type in QUICK:
                self._spawn(self._quick(s))
            elif s.type in MANDATORY:
                if s.type == SignalType.FULL_TIME:
                    self.board.pending.clear()
                self._spawn(self._produce(s))
            else:
                self.board.pending.append(s)

    def tick(self, clock: float) -> None:
        """Called on every frame: release held candidates to the Director."""
        if self.board.pending and clock - self.board.pending[0].second >= DIRECTOR_HOLD_S:
            batch, self.board.pending = self.board.pending, []
            self._spawn(self._direct(batch, clock))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        from .config import close_credentials

        await close_credentials()

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------- director
    async def _direct(self, batch: list[Signal], clock: float) -> None:
        board = self.board
        eligible = []
        for s in batch:
            last = board.last_air_by_type.get(s.type.value, -1e9)
            if s.type in TACTICAL and s.second - last < TACTICAL_COOLDOWN_S and s.importance < 75:
                continue
            eligible.append(s)
        budget = max(0, AIR_BUDGET_PER_5_MIN - board.aired_recently(clock))
        if not eligible or budget == 0:
            await self._emit(self.on_trace, {"agent": "match_director", "action": "hold",
                                             "status": "skipped", "ms": 0,
                                             "note": f"{len(batch)} candidate(s) dropped (budget/cooldown)"})
            return
        chosen = sorted(eligible, key=lambda s: -s.importance)[:budget]
        if len(eligible) > budget or len(eligible) > 1:
            trace: list[AgentStep] = []
            payload = {"air_budget": budget, "minute": self.state.minute,
                       "already_aired": [a["headline"] for a in board.aired[-5:]],
                       "candidates": [{"signal_id": s.signal_id, "type": s.type.value, "minute": s.minute,
                                       "importance": s.importance, "summary": s.summary} for s in eligible]}
            plan, _ = await self._call(self.director, payload, DirectorPlan, trace, "choose what airs")
            if plan and plan.air:
                by_id = {s.signal_id: s for s in eligible}
                picked = [by_id[i] for i in plan.air if i in by_id][:budget]
                if picked:
                    chosen = picked
        for s in chosen:
            self._spawn(self._produce(s))

    # ---------------------------------------------------------------- quick
    async def _quick(self, s: Signal) -> None:
        ev = {e.metric: e.value for e in s.evidence}
        name = self.state.name(s.player_id) if s.player_id else ""
        variants: dict[str, dict[str, Variant]] = {}
        for lang in self.settings.languages:
            L = QUICK_LABELS.get(lang, QUICK_LABELS["en"])
            if s.type == SignalType.SPRINT:
                head, body = f"{name} · {ev.get('speed_kmh', 0):.1f} km/h", L["sprint"]
            elif s.type == SignalType.POWER_SHOT:
                head, body = f"{name} · {ev.get('shot_speed_kmh', 0):.0f} km/h", L["power_shot"]
            elif s.type == SignalType.ELITE_PASS:
                head, body = f"{name} · {ev.get('pass_difficulty', 0):.0f}/100", L["elite_pass"]
            elif s.type == SignalType.PASS_STREAK:
                head, body = f"{name} · {ev.get('consecutive_completed_passes', 0):.0f} {L['pass_streak']}", ""
            elif s.type == SignalType.CARD:
                head, body = f"{L['card']} · {name}", ""
            else:
                head, body = L["substitution"], s.summary if lang == "en" else ""
            v = Variant(headline=head, body=body)
            variants[lang] = {"casual": v, "analyst": Variant(headline=head, body=s.summary if lang == "en" else body)}
        ov = Overlay(overlay_id=uuid.uuid4().hex[:12], match_id=s.match_id, kind=KIND[s.type],
                     show_at_second=s.second, duration_s=5.0, priority=s.importance, headline=variants["en"
                     if "en" in variants else next(iter(variants))]["casual"].headline, body=s.summary,
                     player_id=s.player_id, side=s.side, evidence=s.evidence, verified=True,
                     produced_by=["stats_engine"], minute=s.minute, signal_id=s.signal_id, variants=variants,
                     trace=[AgentStep(agent="stats_engine", action="data tag", note="no LLM needed")])
        await self._publish(ov)

    # -------------------------------------------------------------- produce
    async def _produce(self, s: Signal) -> Optional[Overlay]:
        async with self._sem:
            return await self._produce_inner(s)

    async def _produce_inner(self, s: Signal) -> Overlay:
        trace: list[AgentStep] = [AgentStep(agent="stats_engine", action=f"detected {s.type.value}")]
        facts = self._facts.pop(s.signal_id, None) or self.fact_sheet(s)
        board = self.board
        board.win_prob.append({"minute": s.minute, **facts["win_probability"]})
        sig = s.model_dump(mode="json", exclude={"ground_truth_hint"})
        recent = [f"{a['minute']}' {a['headline']}" for a in board.aired[-4:]]

        note: Optional[AnalystNote] = None
        verdict: Optional[JudgeVerdict] = None
        tool_results: list = []
        if s.type in TACTICAL or s.type in KEY:
            (note, tool_results), (verdict, _) = await asyncio.gather(
                self._call(self.analyst, {"signal": sig, "facts_at_signal_time": facts,
                                          "current_minute": self.state.minute, "earlier_on_air": recent},
                           AnalystNote, trace, "investigate with MCP tools"),
                self._call(self.judge, {"signal": sig, "score": facts["snapshot"]["score"],
                                        "minute": s.minute}, JudgeVerdict, trace, "rate importance"))

        allowed = allowed_numbers(facts, sig, tool_results, note.key_numbers if note else [])
        roster = self.roster()
        teams = set(self.state.team_name.values())

        story_payload: dict[str, Any] = {"signal": sig, "facts": facts, "earlier_on_air": recent}
        if note:
            story_payload["analyst"] = note.model_dump()
        if verdict:
            story_payload["judge"] = verdict.model_dump()

        story: Optional[Story] = None
        status = "ok"
        numbers_ok_draft: Optional[Story] = None  # passed the deterministic check, failed only the LLM check
        for attempt in range(2):
            draft, _ = await self._call(self.storyteller, story_payload, Story, trace,
                                        "write the line" if attempt == 0 else "rewrite after fact-check")
            if draft is None:
                break
            text = f"{draft.headline}. {draft.body}"
            det = check_story(text, allowed, roster, s.summary, extra_names=teams)
            problems = list(det.problems)
            if det.ok:
                numbers_ok_draft = draft
            if det.ok and self.settings.semantic_check and (s.type in TACTICAL or s.type in KEY):
                sem, _ = await self._call(self.factchecker, {
                    "story": draft.model_dump(), "evidence": sig, "facts": facts,
                    "analyst": note.model_dump() if note else None,
                    "judge": verdict.model_dump() if verdict else None},
                    SemanticCheck, trace, "semantic check")
                if sem is not None and not sem.supported:
                    problems += sem.problems or ["Claim not supported by the evidence."]
            if not problems:
                await self._step(trace, "fact_checker", "verify numbers, names, direction", note="approved")
                story = draft
                break
            board.stats["rejections"] += 1
            log.info("fact-check rejected %s at %s': %s", s.type.value, s.minute, "; ".join(problems))
            await self._step(trace, "fact_checker", "verify numbers, names, direction", "rejected",
                             "; ".join(problems)[:240])
            story_payload["feedback"] = problems
        if story is None and numbers_ok_draft is not None:
            # Every number, name and direction checked out; only the stricter wording review objected.
            story = numbers_ok_draft
            status = "numbers"
            await self._step(trace, "fact_checker", "air with numbers verified", "retry",
                             "numbers, names and direction verified; wording review not passed")
        if story is None:
            story = fallback.story(s)
            status = "fallback"
            board.stats["fallbacks"] += 1
            await self._step(trace, "storyteller", "template fallback", "fallback")

        variants = await self._personalise(s, story, allowed, roster, teams, trace)
        terms = glossary_terms((note.glossary_terms if note else []), story.body + " " + s.summary)
        ov = Overlay(
            overlay_id=uuid.uuid4().hex[:12], match_id=s.match_id, kind=KIND.get(s.type, OverlayKind.KEY_MOMENT),
            show_at_second=s.second, duration_s=12.0 if s.type in MANDATORY else 10.0,
            priority=verdict.importance if verdict else s.importance, headline=story.headline, body=story.body,
            player_id=s.player_id, side=s.side, evidence=s.evidence, verified=status == "ok",
            check_level={"ok": "full", "numbers": "numbers"}.get(status, "template"),
            produced_by=list(dict.fromkeys(step.agent for step in trace)), glossary_terms=terms, minute=s.minute,
            signal_id=s.signal_id, importance_reason=verdict.stakes if verdict else None, variants=variants,
            trace=trace, win_probability=facts["win_probability"])
        board.aired.append({"minute": s.minute, "type": s.type.value, "headline": story.headline,
                            "second": s.second, "body": story.body})
        board.last_air_by_type[s.type.value] = s.second
        await self._publish(ov)
        if s.type == SignalType.FULL_TIME:
            await self.write_recap()
        elif s.type == SignalType.HALF_TIME:
            self._spawn(self._half_time_reports())
        return ov

    async def _half_time_reports(self) -> None:
        try:
            await asyncio.gather(*(self.coach_report(side, kind="half_time") for side in ("home", "away")))
        finally:
            self.half_time_done.set()

    async def _personalise(self, s: Signal, story: Story, allowed: set[float], roster: set[str],
                           teams: set[str], trace: list[AgentStep]) -> dict[str, dict[str, Variant]]:
        async def one(lang: str):
            payload = {"language": lang, "story": story.model_dump(), "signal_type": s.type.value,
                       "home_team": self.state.team_name.get("home"), "away_team": self.state.team_name.get("away")}
            fv, _ = await self._call(self.fan_producer, payload, FanVersions, trace, f"personalise ({lang})")
            if fv is not None:
                chk = check_story(f"{fv.analyst_headline}. {fv.analyst_body} {fv.casual_body}", allowed, roster,
                                  s.summary, extra_names=teams)
                if not chk.ok:
                    trace.append(AgentStep(agent="fact_checker", action=f"verify {lang} versions",
                                           status="rejected", note="; ".join(chk.problems)[:200]))
                    fv = None
            if fv is None:
                fv = fallback.fan_versions(story)
            fv.home_fans, fv.away_fans = _unlabel(fv.home_fans, teams), _unlabel(fv.away_fans, teams)
            return lang, {"casual": Variant(headline=fv.casual_headline, body=fv.casual_body),
                          "analyst": Variant(headline=fv.analyst_headline, body=fv.analyst_body),
                          "home_fans": Variant(headline=fv.casual_headline, body=fv.home_fans),
                          "away_fans": Variant(headline=fv.casual_headline, body=fv.away_fans)}

        pairs = await asyncio.gather(*(one(lang) for lang in self.settings.languages))
        return dict(pairs)

    async def _publish(self, ov: Overlay) -> None:
        self.board.overlays.append(ov)
        await self._emit(self.on_overlay, ov)

    # ---------------------------------------------------------------- recap
    async def write_recap(self, stopped_at: Optional[int] = None) -> dict:
        """Full-time recap; with `stopped_at`, a recap of a match the producer ended early."""
        trace: list[AgentStep] = []
        s = self.state
        standout = self.match_tools.get_top_performers("pass_difficulty", 1)
        facts = {"status": f"stopped by the producer at {stopped_at}'" if stopped_at is not None else "full time",
                 "score": self.match_tools.get_match_snapshot()["score"], "teams": s.team_summary(),
                 "standout": standout[0] if standout else {}, "win_probability_history": self.board.win_prob[-8:]}
        moments = [f"{a['minute']}' {a['headline']}: {a['body']}" for a in self.board.aired]
        recap, _ = await self._call(self.recap_writer, {"facts": facts, "moments": moments}, Recap, trace,
                                    "write full-time recap")
        allowed = allowed_numbers(facts, moments)
        if recap is not None:
            text = " ".join([recap.headline, *recap.paragraphs, *recap.key_moments])
            chk = check_story(text, allowed, self.roster(), extra_names=set(s.team_name.values()))
            if not chk.ok:
                trace.append(AgentStep(agent="fact_checker", action="verify recap", status="rejected",
                                       note="; ".join(chk.problems)[:240]))
                recap = None
            else:
                trace.append(AgentStep(agent="fact_checker", action="verify recap", note="approved"))
        if recap is None:
            score = " ".join(f"{k} {v}" for k, v in facts["score"].items())
            label = f"Stopped at {stopped_at}'" if stopped_at is not None else "Full-time"
            recap = Recap(headline=f"{label}: {score}", paragraphs=[f"Final score: {score}."] + moments[:3],
                          key_moments=moments[:6], player_of_the_match=facts["standout"].get("player", ""),
                          player_of_the_match_reason="Highest average pass difficulty in the match.")
            trace.append(AgentStep(agent="storyteller", action="template recap", status="fallback"))
        self.board.recap = {"recap": recap.model_dump(), "facts": facts, "trace": [t.model_dump() for t in trace],
                            "stopped_at": stopped_at}
        await self.translate_recap()
        return self.board.recap

    # ------------------------------------------------------------ ask the pundit
    async def ask(self, question: str, language: str = "en") -> dict:
        """Answer a viewer's question about the live match, grounded in MCP tool results."""
        question = " ".join((question or "").split())[:300]
        trace: list[AgentStep] = []
        if len(question) < 3:
            return {"answer": "Ask me anything about this match.", "verified": False, "trace": []}
        facts = {"snapshot": self.match_tools.get_match_snapshot(), "meters": self.match_tools.get_meters(5),
                 "win_probability": self.match_tools.win_probability()}
        payload: dict[str, Any] = {"QUESTION": question, "LANGUAGE": language, "minute": self.state.minute,
                                   "facts": facts}
        roster, teams = self.roster(), set(self.state.team_name.values())
        result: Optional[PunditAnswer] = None
        verified = False
        for attempt in range(2):
            ans, tool_results = await self._call(self.pundit, payload, PunditAnswer, trace,
                                                 "answer viewer" if attempt == 0 else "re-answer after fact-check")
            if ans is None:
                break
            result = ans
            if not ans.on_topic:
                verified = True
                break
            allowed = allowed_numbers(facts, tool_results, ans.key_numbers)
            chk = check_story(ans.answer, allowed, roster, extra_names=teams)
            if chk.ok:
                await self._step(trace, "fact_checker", "verify answer", note="approved")
                verified = True
                break
            await self._step(trace, "fact_checker", "verify answer", "rejected", "; ".join(chk.problems)[:200])
            payload["feedback"] = chk.problems
        if result is None:
            m = facts["meters"]["control_vs_chaos"]
            text = (f"At {self.state.minute}' it is {' '.join(f'{k} {v}' for k, v in facts['snapshot']['score'].items())}."
                    f" The game is {m['label']} right now.")
            return {"answer": text, "verified": False, "terms": [], "trace": [t.model_dump() for t in trace]}
        return {"answer": result.answer, "verified": verified, "on_topic": result.on_topic,
                "terms": glossary_terms(result.glossary_terms, result.answer),
                "numbers": [k.model_dump() for k in result.key_numbers], "minute": self.state.minute,
                "trace": [t.model_dump() for t in trace]}

    # ------------------------------------------------------------ coach report
    async def coach_report(self, side: str, kind: str = "on_demand") -> dict:
        """Half-time report for one club's staff: what works, what doesn't, three changes."""
        team = self.state.team_name.get(side, side)
        trace: list[AgentStep] = []
        facts = {"club": team, "side": side, "snapshot": self.match_tools.get_match_snapshot(),
                 "meters": self.match_tools.get_meters(15), "own_shape": self.match_tools.get_team_shape(side, 10),
                 "opponent_shape": self.match_tools.get_team_shape("away" if side == "home" else "home", 10),
                 "top_passers": self.match_tools.get_top_performers("pass_difficulty", 3)}
        payload: dict[str, Any] = {"CLUB": team, "minute": self.state.minute, "facts": facts}
        roster, teams = self.roster(), set(self.state.team_name.values())
        report: Optional[CoachReport] = None
        verified = False
        for attempt in range(2):
            rep, tool_results = await self._call(self.coach, payload, CoachReport, trace,
                                                 f"half-time report for {team}")
            if rep is None:
                break
            report = rep
            text = " ".join([rep.headline, *rep.working, *rep.not_working,
                             *[f"{c.change} {c.why}" for c in rep.changes]])
            chk = check_story(text, allowed_numbers(facts, tool_results), roster, extra_names=teams)
            if chk.ok:
                await self._step(trace, "fact_checker", "verify coach report", note="approved")
                verified = True
                break
            await self._step(trace, "fact_checker", "verify coach report", "rejected", "; ".join(chk.problems)[:200])
            payload["feedback"] = chk.problems
        doc = {"side": side, "club": team, "minute": payload["minute"], "kind": kind, "verified": verified,
               "report": report.model_dump() if report else None, "facts": facts,
               "trace": [t.model_dump() for t in trace]}
        self.board.coach_reports[side] = doc
        await self._emit(self.on_coach, doc)
        return doc

    # ------------------------------------------------------------ recap in every language
    async def translate_recap(self) -> None:
        rec = (self.board.recap or {}).get("recap")
        if not rec:
            return
        out: dict[str, dict] = {"en": {"headline": rec["headline"], "paragraphs": rec["paragraphs"]}}
        trace: list[AgentStep] = []

        async def one(lang: str):
            tr, _ = await self._call(self.translator, {"LANGUAGE": lang, "RECAP": out["en"]}, RecapTranslation,
                                     trace, f"translate recap ({lang})")
            if tr is not None:
                out[lang] = tr.model_dump()

        await asyncio.gather(*(one(lang) for lang in self.settings.languages if lang != "en"))
        self.board.recap["translations"] = out
