"""Overlay contract: timed, machine-readable insight cards for the render layer.

A graphics partner (or our web app) can draw these over a live feed. Every
overlay carries the evidence that justifies it, so the "Why?" panel never has
to call an LLM.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OverlayKind(str, Enum):
    PLAYER_TAG = "player_tag"        # name + speed/distance threshold triggers
    PASS_QUALITY = "pass_quality"
    SHOT_SPEED = "shot_speed"
    TACTICAL_SHIFT = "tactical_shift"
    KEY_MOMENT = "key_moment"
    MILESTONE = "milestone"
    METER_UPDATE = "meter_update"    # control/chaos, pressure, rhythm
    MATCH_STATUS = "match_status"    # half-time / full-time cards
    RECAP = "recap"


class Evidence(BaseModel):
    metric: str
    value: float
    baseline: Optional[float] = None
    window: Optional[str] = None  # e.g. "55'-62'"
    source_tool: Optional[str] = None  # MCP tool that produced it


class Variant(BaseModel):
    """One audience's version of an insight in one language."""

    headline: str
    body: str = ""


class AgentStep(BaseModel):
    """One hop in the agent crew's handoff chain, shown in the Producer view."""

    agent: str
    action: str
    status: Literal["ok", "retry", "rejected", "fallback", "skipped", "error"] = "ok"
    ms: int = 0
    note: Optional[str] = None


class Overlay(BaseModel):
    overlay_id: str
    match_id: str
    kind: OverlayKind
    show_at_second: float
    duration_s: float = 8.0
    priority: int = Field(50, ge=0, le=100)
    headline: str
    body: Optional[str] = None
    audience: Literal["all", "casual", "analyst"] = "all"
    language: str = "en"
    player_id: Optional[str] = None
    side: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)
    verified: bool = False
    produced_by: list[str] = Field(default_factory=list)  # agent trail
    glossary_terms: list[str] = Field(default_factory=list)
    minute: int = 0
    signal_id: Optional[str] = None
    importance_reason: Optional[str] = None
    # variants[language][audience] where audience is casual | analyst | home_fans | away_fans
    variants: dict[str, dict[str, Variant]] = Field(default_factory=dict)
    trace: list[AgentStep] = Field(default_factory=list)
    win_probability: Optional[dict[str, float]] = None
