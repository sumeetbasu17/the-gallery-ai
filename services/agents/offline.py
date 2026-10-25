"""ScriptedChatClient: a deterministic, network-free stand-in for the LLM.

It speaks the same Agent Framework protocol as the real clients (including
tool calls), so the whole crew - handoffs, MCP tools, fact-check retries and
fallbacks - can be exercised in tests and demos without Azure. Outputs are
plain but always grounded in the facts it was given.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

_ROLE = re.compile(r"\[role:(\w+)\]")

TOOL_PLAN = {"analyst": ("get_team_shape", "team"), "judge": ("win_probability", None),
             "pundit": ("get_meters", None), "coach": ("get_meters", None)}

PHRASES = {
    "hi": {"Tactical shift": "रणनीतिक बदलाव", "GOAL!": "गोल!", "Momentum swing": "मोमेंटम बदला"},
    "es": {"Tactical shift": "Cambio táctico", "GOAL!": "¡GOL!", "Momentum swing": "Cambio de inercia"},
}


def _texts(messages) -> tuple[str, str, list[str]]:
    system, user, results = "", "", []
    for m in messages:
        for c in m.contents:
            if c.type == "text":
                if m.role == "system":
                    system += c.text
                elif m.role == "user":
                    user += c.text
            elif c.type == "function_result":
                results.append(str(c.result))
    return system, user, results


def _payload(user: str) -> dict[str, Any]:
    start = user.find("{")
    try:
        return json.loads(user[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        return {}


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    OTEL_PROVIDER_NAME = "offline"

    def __init__(self, fail_roles: set[str] | None = None, bad_story_once: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.fail_roles = fail_roles or set()
        self.bad_story_once = bad_story_once
        self.calls: list[str] = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        system, user, results = _texts(messages)
        instructions = options.get("instructions") or ""
        m = _ROLE.search(system) or _ROLE.search(instructions) or _ROLE.search(user)
        role = m.group(1) if m else "unknown"
        self.calls.append(role)
        if role in self.fail_roles:
            raise RuntimeError(f"simulated outage for {role}")
        data = _payload(user)

        plan = TOOL_PLAN.get(role)
        if plan and options.get("tools") and not results:
            name, arg = plan
            args = {arg: data.get("signal", {}).get("side") or "home"} if arg else {}
            call = Content.from_function_call(call_id=f"{role}-1", name=name, arguments=args)
            return ChatResponse(messages=[Message(role="assistant", contents=[call])])

        out = getattr(self, f"_{role}", lambda d, r: {})(data, results)
        return ChatResponse(messages=[Message(role="assistant", contents=[json.dumps(out, ensure_ascii=False)])])

    # --- role scripts --------------------------------------------------------
    def _director(self, d, _):
        cands = sorted(d.get("candidates", []), key=lambda c: -c.get("importance", 0))
        budget = int(d.get("air_budget", 2))
        return {"air": [c["signal_id"] for c in cands[:budget]], "reason": "Highest-importance moments first."}

    def _analyst(self, d, results):
        sig = d.get("signal", {})
        nums = [{"metric": e["metric"], "value": e["value"]} for e in sig.get("evidence", [])][:3]
        summary = sig.get("summary", "").lower()
        terms = [t for t, cue in (("low block", "low block"), ("mid block", "mid block"),
                                  ("high block", "high block"), ("pressing", "pressing"),
                                  ("playing narrow", "narrowed")) if cue in summary]
        return {"observation": sig.get("summary", ""),
                "explanation": "The shape change shows in the tracking data over the last few minutes.",
                "key_numbers": nums, "glossary_terms": terms}

    def _judge(self, d, results):
        imp = int(d.get("signal", {}).get("importance", 50))
        return {"importance": imp, "stakes": "It shifts the balance of the match."}

    def _storyteller(self, d, _):
        sig = d.get("signal", {})
        if self.bad_story_once:
            self.bad_story_once = False
            return {"headline": "Shift", "body": sig.get("summary", "") + " They now average 999 passes."}
        head = {"goal": "GOAL!", "block_shift": "Tactical shift", "momentum_swing": "Momentum swing"}.get(
            sig.get("type", ""), "Match insight")
        return {"headline": head, "body": sig.get("summary", "")}

    def _factchecker(self, d, _):
        return {"supported": True, "problems": []}

    def _fanproducer(self, d, _):
        st, lang = d.get("story", {}), d.get("language", "en")
        head = PHRASES.get(lang, {}).get(st.get("headline", ""), st.get("headline", ""))
        body = st.get("body", "")
        return {"casual_headline": head, "casual_body": body, "analyst_headline": head, "analyst_body": body,
                "home_fans": body, "away_fans": body}

    def _recap(self, d, _):
        facts = d.get("facts", {})
        moments = d.get("moments", [])
        score = facts.get("score", {})
        line = " ".join(f"{k} {v}" for k, v in score.items())
        status = facts.get("status", "full time")
        label, lead = ("Full-time", "Final score") if status == "full time" else ("Stopped early", f"Match {status}. Score")
        return {"headline": f"{label}: {line}", "paragraphs": [f"{lead}: {line}."] +
                [m for m in moments[:3]], "key_moments": moments[:6],
                "player_of_the_match": facts.get("standout", {}).get("player", ""),
                "player_of_the_match_reason": "Led the match for difficult passes completed."}

    def _scenario(self, d, _):
        return {}

    def _pundit(self, d, _):
        facts = d.get("facts", {})
        score = " ".join(f"{k} {v}" for k, v in facts.get("snapshot", {}).get("score", {}).items())
        label = facts.get("meters", {}).get("control_vs_chaos", {}).get("label", "contested")
        return {"answer": f"At {d.get('minute', 0)}' the score is {score}, and the game is {label} right now.",
                "key_numbers": [], "glossary_terms": ["control vs chaos"], "on_topic": True}

    def _coach(self, d, _):
        club = d.get("CLUB", "the team")
        shape = d.get("facts", {}).get("own_shape", {}).get("recent") or {}
        line = shape.get("defensive_line_m", 0)
        return {"headline": f"{club}: half-time priorities",
                "working": [f"Defensive line held at {line} m from goal."],
                "not_working": ["Too many turnovers in midfield."],
                "changes": [{"change": "Press higher on the opponent's first pass.", "why": "Their line is deep."},
                            {"change": "Switch play to the weak side earlier.", "why": "Space opens wide."},
                            {"change": "Keep a midfielder back in rest defence.", "why": "Protects against counters."}]}

    def _translator(self, d, _):
        rec = d.get("RECAP", {})
        return {"headline": rec.get("headline", ""), "paragraphs": rec.get("paragraphs", [])}
