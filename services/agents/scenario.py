"""Scenario Writer agent: turns a one-line storyline into a playable tactical timeline."""

from __future__ import annotations

import json
import random
import re

from agent_framework import Agent

from simulator.scenarios import BLOCKS, WIDTHS

from . import prompts
from .config import Settings, make_client
from .contracts import Scenario

_REAL_CLUB_WORDS = re.compile(
    r"\b(arsenal|chelsea|liverpool|manchester|man utd|tottenham|spurs|everton|newcastle|aston villa|"
    r"west ham|brighton|fulham|brentford|wolves|wolverhampton|crystal palace|nottingham|bournemouth|"
    r"leicester|leeds|southampton|burnley|sunderland|premier league|real madrid|barcelona|bayern)\b", re.I)


def offline_scenario(brief: str, seed: int = 0) -> dict:
    """Deterministic interpretation of a brief, used without a model or as a fallback."""
    b = brief.lower()
    rng = random.Random(seed or len(brief))

    def plan(press_early: bool, sit_late: bool) -> list[dict]:
        rows = [{"from_minute": 0, "block": "high" if press_early else "mid", "width": "balanced",
                 "press_intensity": 0.8 if press_early else 0.5, "tempo": 0.6}]
        if sit_late:
            rows.append({"from_minute": rng.choice([55, 60, 65]), "block": "low", "width": "narrow",
                         "press_intensity": 0.2, "tempo": 0.35})
        return rows

    score = None
    m = re.search(r"\b(\d)\s*[-–]\s*(\d)\b", b)
    n = re.search(r"\b(\d{1,2})[- ]goal", b)
    if m:
        score = {"home": int(m.group(1)), "away": int(m.group(2))}
    elif n:
        total = min(12, int(n.group(1)))
        score = {"home": (total + 1) // 2, "away": total // 2}
    reds = [{"side": "away" if "northgate" in b.split("red")[0][-60:] or "riverside" not in b else "home",
             "minute": 35 if "first-half" in b or "first half" in b else 60}] if "red card" in b or "sent off" in b else []
    home_sits = "riverside" in b and any(w in b for w in ("bus", "low block", "sit", "defend"))
    away_sits = not home_sits
    return {"title": "Storyline", "storyline": brief or "A tactical battle.", "final_score": score,
            "red_cards": reds,
            "home": {"name": "Riverside Athletic", "short_name": "Riverside", "formation": "4-3-3",
                     "identity": "Possession and wing play.", "plan": plan("press" in b and "riverside" in b, home_sits)},
            "away": {"name": "Northgate United", "short_name": "Northgate", "formation": "4-2-3-1",
                     "identity": "Compact and direct.", "plan": plan("press" in b and "northgate" in b, away_sits)}}


async def write_scenario(settings: Settings, brief: str) -> dict:
    """Ask the Scenario Writer for a timeline; validate it; fall back to a rule-based reading."""
    brief = (brief or "").strip()[:400]
    if settings.mode == "offline" or not brief:
        return offline_scenario(brief)
    agent = Agent(make_client(settings, settings.creative_model), prompts.SCENARIO, name="scenario_writer")
    payload = {"brief": brief, "clubs": ["Riverside Athletic (home)", "Northgate United (away)"],
               "allowed": {"block": BLOCKS, "width": WIDTHS, "formation": ["4-3-3", "4-2-3-1"]},
               "rule": "Keep the two club names exactly. Changes at least 10 minutes apart."}
    try:
        resp = await agent.run(json.dumps(payload), options={"response_format": Scenario})
        sc = resp.value or Scenario.model_validate_json(resp.text)
        data = sc.model_dump()
        if _REAL_CLUB_WORDS.search(json.dumps(data)):
            raise ValueError("scenario mentioned a real club")
        data["home"]["name"], data["away"]["name"] = "Riverside Athletic", "Northgate United"
        return data
    except Exception:  # noqa: BLE001 - never block kick-off on the writer
        return offline_scenario(brief)
