"""Signals: deterministic findings the stats engine hands to the agent crew.

A signal is a fact plus its evidence. Agents may phrase it, rank it and
personalise it, but they may not change its numbers.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from gallery_schema.overlays import Evidence


class SignalType(str, Enum):
    GOAL = "goal"
    BIG_CHANCE = "big_chance"            # shot with xG >= 0.25
    POWER_SHOT = "power_shot"            # shot speed threshold
    SPRINT = "sprint"                    # player top-speed threshold
    ELITE_PASS = "elite_pass"            # completed pass with difficulty >= 70
    PASS_STREAK = "pass_streak"          # player milestone: consecutive completions
    BLOCK_SHIFT = "block_shift"          # defensive line moved (high/mid/low)
    WIDTH_SHIFT = "width_shift"          # team shape narrowed/widened
    PRESS_SHIFT = "press_shift"          # PPDA changed markedly
    MOMENTUM_SWING = "momentum_swing"    # control meter swung
    CARD = "card"
    SUBSTITUTION = "substitution"
    HALF_TIME = "half_time"
    FULL_TIME = "full_time"


class Signal(BaseModel):
    signal_id: str
    match_id: str
    type: SignalType
    second: float
    minute: int
    side: Optional[str] = None
    player_id: Optional[str] = None
    importance: int = Field(50, ge=0, le=100)
    summary: str                       # neutral, factual one-liner (no adjectives)
    evidence: list[Evidence] = Field(default_factory=list)
    ground_truth_hint: Optional[str] = None  # filled only in evaluation runs
