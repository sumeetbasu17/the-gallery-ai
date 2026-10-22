"""Shared event contracts for The Gallery.

Every service (simulator, stats engine, MCP server, agents, web) speaks these
types. Coordinates use a 105 x 68 metre pitch: x runs from the home goal (0)
to the away goal (105), y from the bottom touchline (0) to the top (68).
All clubs, players and matches are fictional and synthetic.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0


class Side(str, Enum):
    HOME = "home"
    AWAY = "away"


class EventType(str, Enum):
    KICK_OFF = "kick_off"
    PASS = "pass"
    CARRY = "carry"
    SHOT = "shot"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    PRESSURE = "pressure"
    FOUL = "foul"
    CARD = "card"
    POSSESSION_CHANGE = "possession_change"
    GOAL = "goal"
    SUBSTITUTION = "substitution"
    HALF_TIME = "half_time"
    FULL_TIME = "full_time"


class Point(BaseModel):
    x: float = Field(ge=0, le=PITCH_LENGTH)
    y: float = Field(ge=0, le=PITCH_WIDTH)


class Player(BaseModel):
    id: str
    name: str
    number: int
    position: str  # e.g. GK, RB, CB, LB, DM, CM, AM, RW, LW, ST
    side: Side


class TacticalProfile(BaseModel):
    """Ground truth the simulator plays out; detectors are scored against it."""

    from_minute: int
    block: Literal["high", "mid", "low"] = "mid"
    width: Literal["wide", "balanced", "narrow"] = "balanced"
    press_intensity: float = Field(0.5, ge=0, le=1)
    tempo: float = Field(0.5, ge=0, le=1)


class Team(BaseModel):
    id: str
    name: str
    short_name: str
    side: Side
    formation: str
    players: list[Player]
    tactics: list[TacticalProfile]


class MatchMetadata(BaseModel):
    match_id: str
    competition: str = "Synthetic League"
    venue: str
    home: Team
    away: Team
    seed: int


class MatchEvent(BaseModel):
    """One timestamped on-ball or match-state event."""

    event_id: str
    match_id: str
    seq: int
    type: EventType
    minute: int
    second: float  # seconds since kick-off of the match clock
    side: Optional[Side] = None
    player_id: Optional[str] = None
    target_player_id: Optional[str] = None
    start: Optional[Point] = None
    end: Optional[Point] = None
    outcome: Optional[Literal["success", "fail", "on_target", "off_target", "blocked", "goal", "saved"]] = None
    # Derived-at-source physical measures (synthetic ground truth)
    ball_speed_kmh: Optional[float] = None
    under_pressure: bool = False
    xg: Optional[float] = None
    detail: dict = Field(default_factory=dict)


class PlayerFrame(BaseModel):
    player_id: str
    x: float
    y: float
    speed_kmh: float


class TrackingFrame(BaseModel):
    """Positions of all 22 players plus the ball, emitted every second."""

    match_id: str
    second: float
    ball: Point
    players: list[PlayerFrame]


class Envelope(BaseModel):
    """What travels on the stream: exactly one of event or frame."""

    kind: Literal["event", "frame", "metadata"]
    event: Optional[MatchEvent] = None
    frame: Optional[TrackingFrame] = None
    metadata: Optional[MatchMetadata] = None
