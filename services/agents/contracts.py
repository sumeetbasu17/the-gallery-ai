"""Structured outputs each agent must return (enforced via response_format)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeyNumber(BaseModel):
    metric: str
    value: float
    unit: str = ""


class AnalystNote(BaseModel):
    """Tactical Analyst: what changed, why, and the numbers that prove it."""

    observation: str = Field(description="What is happening on the pitch, factual, one sentence.")
    explanation: str = Field(description="The tactical cause or mechanism, one or two sentences.")
    key_numbers: list[KeyNumber] = Field(default_factory=list, description="Numbers copied exactly from tools.")
    glossary_terms: list[str] = Field(default_factory=list, description="Jargon used, e.g. 'low block'.")


class JudgeVerdict(BaseModel):
    """Moment Judge: how much this matters to the result, and why."""

    importance: int = Field(ge=0, le=100)
    stakes: str = Field(description="Why this matters for the result, one sentence, using win probability.")


class Story(BaseModel):
    """Storyteller: the broadcast line."""

    headline: str = Field(description="At most 70 characters.")
    body: str = Field(description="At most 2 sentences, broadcast voice.")


class SemanticCheck(BaseModel):
    """Fact-Checker (LLM pass): does the story claim anything the evidence does not support?"""

    supported: bool
    problems: list[str] = Field(default_factory=list)


class FanVersions(BaseModel):
    """Fan Producer: the same verified insight for four audiences, in one language."""

    casual_headline: str
    casual_body: str = Field(description="Plain language, no jargon without a short explanation.")
    analyst_headline: str
    analyst_body: str = Field(description="Dense, numbers-first.")
    home_fans: str = Field(description="One line written for home supporters.")
    away_fans: str = Field(description="One line written for away supporters.")


class DirectorPlan(BaseModel):
    """Match Director: which candidate moments go on air, in what order."""

    air: list[str] = Field(description="signal_ids to air, most important first.")
    reason: str


class Recap(BaseModel):
    headline: str
    paragraphs: list[str] = Field(description="Three to five short paragraphs.")
    key_moments: list[str] = Field(description="Three to six one-line bullet moments with minutes.")
    player_of_the_match: str
    player_of_the_match_reason: str


class TeamPlan(BaseModel):
    from_minute: int = Field(ge=0, le=89)
    block: str = Field(description="high | mid | low")
    width: str = Field(description="wide | balanced | narrow")
    press_intensity: float = Field(ge=0, le=1)
    tempo: float = Field(ge=0, le=1)


class ClubIdea(BaseModel):
    name: str
    short_name: str
    formation: str = Field(description="4-3-3 or 4-2-3-1")
    identity: str = Field(description="One sentence describing the club's playing identity.")
    plan: list[TeamPlan] = Field(description="Tactical timeline, first entry from_minute 0.")


class Scenario(BaseModel):
    """Scenario Writer: a storyline for a synthetic match, as data the simulator can play."""

    title: str
    storyline: str
    home: ClubIdea
    away: ClubIdea
