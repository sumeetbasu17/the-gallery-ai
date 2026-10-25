"""Pure metric functions: pass difficulty, xG helpers, block classification.

Kept free of state so they are easy to test and to explain in the "Why?" panel.
"""

from __future__ import annotations

from gallery_schema.events import MatchEvent

# Thresholds calibrated against simulator ground truth (see tests/test_stats_engine.py)
LOW_BLOCK_MAX_M = 25.0    # ball-adjusted mean distance of the deepest four outfielders from own goal
HIGH_BLOCK_MIN_M = 36.0
NARROW_MAX_M = 30.0       # out-of-possession team width
WIDE_MIN_M = 38.0
SPRINT_KMH = 25.0
SPRINT_MIN_S = 2  # seconds above SPRINT_KMH before a run counts as a sprint
SPRINT_END_KMH = 19.0  # a sprint ends when the player drops below this
TOP_SPEED_TAG_KMH = 33.0
POWER_SHOT_KMH = 100.0


def pass_difficulty(ev: MatchEvent) -> int:
    """0-100 difficulty rating for a pass.

    Components (each explainable on screen):
      distance   up to 35 pts (long passes are harder)
      pressure   20 pts if the passer was under pressure
      lines      up to 30 pts for defenders bypassed
      lofted     5 pts
      zone       up to 10 pts for passes ending in the final third
    """
    d = ev.detail or {}
    distance = float(d.get("distance_m", 0.0))
    score = min(35.0, max(0.0, distance - 8) * 1.0)
    if ev.under_pressure:
        score += 20
    score += min(30.0, 7.5 * int(d.get("lines_broken", 0)))
    if d.get("lofted"):
        score += 5
    if ev.end is not None and ev.side is not None:
        end_x = ev.end.x if ev.side.value == "home" else 105 - ev.end.x
        if end_x > 70:
            score += min(10.0, (end_x - 70) / 3.5)
    return int(round(min(100.0, score)))


def difficulty_components(ev: MatchEvent) -> dict[str, float]:
    d = ev.detail or {}
    return {
        "distance_m": float(d.get("distance_m", 0.0)),
        "under_pressure": float(ev.under_pressure),
        "lines_broken": float(d.get("lines_broken", 0)),
        "lofted": float(bool(d.get("lofted"))),
    }


def classify_block(line_height_m: float) -> str:
    if line_height_m < LOW_BLOCK_MAX_M:
        return "low"
    if line_height_m >= HIGH_BLOCK_MIN_M:
        return "high"
    return "mid"


def classify_width(width_m: float) -> str:
    if width_m < NARROW_MAX_M:
        return "narrow"
    if width_m >= WIDE_MIN_M:
        return "wide"
    return "balanced"
