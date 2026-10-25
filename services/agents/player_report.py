"""Player report: a short, fact-checked summary of one player's match (live or archived)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from agent_framework import Agent

from . import prompts
from .config import Settings, make_client
from .contracts import PlayerReport
from .factcheck import allowed_numbers, check_story

log = logging.getLogger("gallery.player_report")


def template_report(facts: dict[str, Any]) -> dict:
    s = facts.get("stats", {})
    name = s.get("player", "The player")
    z = facts.get("zones", {})
    where = max(("defensive third", z.get("defensive_third_pct", 0)), ("middle third", z.get("middle_third_pct", 0)),
                ("attacking third", z.get("attacking_third_pct", 0)), key=lambda kv: kv[1])[0]
    events = ", ".join(f"{e['type']} {e['minute']}'" for e in facts.get("events", [])) or "no goals or cards"
    return {"headline": f"{name}: {s.get('passes', 0)} passes, {s.get('shots', 0)} shots",
            "summary": f"{name} spent most of the time in the {where}. They made {s.get('passes', 0)} passes "
                       f"and had {s.get('shots', 0)} shots ({s.get('shots_on_target', 0)} on target). "
                       f"Key events: {events}.",
            "key_numbers": []}


async def write_player_report(settings: Settings, facts: dict[str, Any], language: str, roster: set[str],
                              teams: set[str], client: Optional[Any] = None) -> dict:
    """Ask the player-report agent, fact-check the numbers and names, retry once, else use a template."""
    agent = Agent(client or make_client(settings, settings.creative_model), prompts.PLAYER_REPORT,
                  name="player_report")
    payload: dict[str, Any] = {"LANGUAGE": language, "STATUS": facts.get("status"), "FACTS": facts}
    allowed = allowed_numbers(facts)
    for _ in range(2):
        try:
            resp = await agent.run(json.dumps(payload, ensure_ascii=False, default=str),
                                   options={"response_format": PlayerReport})
            rep = resp.value or PlayerReport.model_validate_json(resp.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("player report failed: %s", exc)
            break
        chk = check_story(f"{rep.headline}. {rep.summary}", allowed, roster, extra_names=teams)
        if chk.ok:
            return {**rep.model_dump(), "verified": True}
        payload["feedback"] = chk.problems
    return {**template_report(facts), "verified": False}
