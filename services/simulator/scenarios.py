"""Tactical scenarios: turn a storyline (from the Scenario Writer agent or a random draw) into teams.

A scenario only changes *how* the fictional clubs play over time. Because the
timeline is known, every generated match comes with ground-truth labels.
"""

from __future__ import annotations

import random
from typing import Any

from gallery_schema.events import TacticalProfile, Team

from .clubs import northgate_united, riverside_athletic
from .formations import FORMATIONS

BLOCKS = ("high", "mid", "low")
WIDTHS = ("wide", "balanced", "narrow")


def _clean_plan(plan: list[dict[str, Any]]) -> list[TacticalProfile]:
    rows = []
    for p in plan or []:
        try:
            rows.append(TacticalProfile(
                from_minute=max(0, min(85, int(p.get("from_minute", 0)))),
                block=p.get("block") if p.get("block") in BLOCKS else "mid",
                width=p.get("width") if p.get("width") in WIDTHS else "balanced",
                press_intensity=max(0.0, min(1.0, float(p.get("press_intensity", 0.5)))),
                tempo=max(0.0, min(1.0, float(p.get("tempo", 0.5)))),
            ))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r.from_minute)
    # keep changes at least 10 minutes apart so each phase is long enough to detect
    out: list[TacticalProfile] = []
    for r in rows:
        if not out or r.from_minute - out[-1].from_minute >= 10:
            out.append(r)
    if not out or out[0].from_minute != 0:
        out.insert(0, TacticalProfile(from_minute=0))
    return out[:4]


def teams_from_scenario(scenario: dict[str, Any]) -> tuple[Team, Team]:
    home, away = riverside_athletic(), northgate_united()
    for team, key in ((home, "home"), (away, "away")):
        spec = scenario.get(key) or {}
        team.tactics = _clean_plan(spec.get("plan", []))
        if spec.get("formation") in FORMATIONS:
            team.formation = spec["formation"]
    return home, away


def random_scenario(seed: int) -> dict[str, Any]:
    """A plausible random tactical story, for bulk dataset generation."""
    rng = random.Random(seed)

    def plan() -> list[dict[str, Any]]:
        phases = [0] + sorted(rng.sample(range(25, 80, 5), rng.randint(0, 2)))
        return [{"from_minute": m, "block": rng.choice(BLOCKS), "width": rng.choice(WIDTHS),
                 "press_intensity": round(rng.uniform(0.15, 0.85), 2), "tempo": round(rng.uniform(0.3, 0.75), 2)}
                for m in phases]

    return {"title": f"Random scenario {seed}", "storyline": "Randomly drawn tactical timeline.",
            "home": {"formation": rng.choice(list(FORMATIONS)), "plan": plan()},
            "away": {"formation": rng.choice(list(FORMATIONS)), "plan": plan()}}


def ground_truth(home: Team, away: Team) -> list[dict[str, Any]]:
    """Tactical changes that a perfect detector would report."""
    labels = []
    for team in (home, away):
        prev = team.tactics[0]
        for t in team.tactics[1:]:
            labels.append({"side": team.side.value, "team": team.name, "minute": t.from_minute,
                           "block": [prev.block, t.block], "width": [prev.width, t.width],
                           "press": [prev.press_intensity, t.press_intensity]})
            prev = t
    return labels


# ---------------------------------------------------------------- storyline outcomes
BASE_GOALS_PER_TEAM = 1.15  # what one side scores on average at finishing 1.0


def sim_kwargs(scenario: dict[str, Any] | None) -> dict[str, Any]:
    """Simulator options a scenario carries (goal-count finishing, red cards)."""
    sim = (scenario or {}).get("sim") or {}
    return {"finishing": sim.get("finishing"), "red_cards": (scenario or {}).get("red_cards") or None,
            "player_finishing": sim.get("player_finishing")}


def build_match(scenario: dict[str, Any] | None, seed: int, with_frames: bool = True):
    from .clubs import northgate_united, riverside_athletic
    from .engine import MatchSimulator

    home, away = teams_from_scenario(scenario) if scenario else (riverside_athletic(), northgate_united())
    return MatchSimulator(home, away, seed=seed, **sim_kwargs(scenario)).run(with_frames=with_frames)


def fit_outcome(scenario: dict[str, Any], seed: int, tries: int = 150, budget_s: float = 12.0) -> tuple[int, dict[str, Any]]:
    """Make the storyline's score come true: tune finishing, then pick the seed that lands on it.

    The simulator stays honest (goals still come from chances); we only choose which of many plausible
    matches to play. Returns (seed, scenario with the chosen settings and the real final score).
    """
    target = scenario.get("final_score") or {}
    th, ta = target.get("home"), target.get("away")
    if th is None or ta is None:
        return seed, scenario
    th, ta = max(0, min(9, int(th))), max(0, min(9, int(ta)))
    # named scorers ("Ndiaye scores twice"): give them sharper finishing and count their goals too
    home_t, away_t = teams_from_scenario(scenario)
    ids = {p.name.lower(): p.id for t in (home_t, away_t) for p in t.players}
    wanted: dict[str, int] = {}
    for sc in scenario.get("scorers") or []:
        name = str(sc.get("player", "")).lower().strip()
        pid = ids.get(name) or next((v for k, v in ids.items() if name and name.split()[-1] in k), None)
        if pid and int(sc.get("goals", 0)) > 0:
            wanted[pid] = min(5, int(sc["goals"]))
    pfin = {pid: 2.5 + g for pid, g in wanted.items()}
    fin = {"home": max(0.3, min(12.0, (th + 0.3) / BASE_GOALS_PER_TEAM)),
           "away": max(0.3, min(12.0, (ta + 0.3) / BASE_GOALS_PER_TEAM))}
    import time

    deadline = time.monotonic() + budget_s
    best = (10**9, seed, fin, (0, 0), {})
    for i in range(tries):
        if time.monotonic() > deadline:
            break
        s = seed + i * 7919
        trial = {**scenario, "sim": {"finishing": fin, "player_finishing": pfin}}
        m = build_match(trial, s, with_frames=False)
        goals = [e for e in m.events if e.type.value == "goal"]
        h = sum(1 for e in goals if e.side.value == "home")
        a = sum(1 for e in goals if e.side.value == "away")
        got = {pid: sum(1 for e in goals if e.player_id == pid) for pid in wanted}
        miss = 2 * (abs(h - th) + abs(a - ta)) + sum(abs(got[p] - g) for p, g in wanted.items())
        if miss < best[0]:
            best = (miss, s, dict(fin), (h, a), got)
        if miss == 0:
            break
        # nudge finishing towards the target as we go
        fin["home"] = max(0.3, min(12.0, fin["home"] * (1 + 0.35 * (th - h) / (th + 1))))
        fin["away"] = max(0.3, min(12.0, fin["away"] * (1 + 0.35 * (ta - a) / (ta + 1))))
    _, s, fin, (h, a), got = best
    names = {v: k for k, v in ids.items()}
    return s, {**scenario, "sim": {"finishing": fin, "player_finishing": pfin, "seed": s,
                                   "score": {"home": h, "away": a},
                                   "scorers": [{"player": names[p].title(), "wanted": wanted[p], "got": got.get(p, 0)}
                                               for p in wanted]}}
