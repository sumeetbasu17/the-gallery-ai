"""Structured outputs each agent must return (enforced via response_format)."""

from __future__ import annotations

from typing import Optional

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


class FinalScore(BaseModel):
    home: int = Field(ge=0, le=9)
    away: int = Field(ge=0, le=9)


class RedCard(BaseModel):
    side: str = Field(description="home | away")
    minute: int = Field(ge=1, le=88)


class ScorerWish(BaseModel):
    player: str = Field(description="Exact player name from the squad lists.")
    goals: int = Field(ge=1, le=5)


class Scenario(BaseModel):
    """Scenario Writer: a storyline for a synthetic match, as data the simulator can play."""

    title: str
    storyline: str
    home: ClubIdea
    away: ClubIdea
    final_score: Optional[FinalScore] = Field(None, description="Only if the brief implies a result or goal count.")
    red_cards: list[RedCard] = Field(default_factory=list, description="Only if the brief mentions a sending-off.")
    scorers: list[ScorerWish] = Field(default_factory=list, description="Only players the brief names as scorers.")


class PunditAnswer(BaseModel):
    """Ask the pundit: an answer grounded in tool results."""

    answer: str = Field(description="Two to four sentences answering the viewer, in the requested language.")
    key_numbers: list[KeyNumber] = Field(default_factory=list, description="Numbers used, copied from tools.")
    glossary_terms: list[str] = Field(default_factory=list)
    on_topic: bool = Field(True, description="False if the question is not about this match.")


class CoachChange(BaseModel):
    change: str = Field(description="One concrete tactical adjustment.")
    why: str = Field(description="The evidence that motivates it, one sentence.")


class CoachReport(BaseModel):
    """Half-time coach report for one club."""

    headline: str
    working: list[str] = Field(description="Two or three things going well, each backed by a number.")
    not_working: list[str] = Field(description="Two or three problems, each backed by a number.")
    changes: list[CoachChange] = Field(description="Exactly three tactical changes to consider.")


class RecapTranslation(BaseModel):
    headline: str
    paragraphs: list[str]


class PlayerReport(BaseModel):
    """A short, analyst-ready summary of one player's match."""

    headline: str = Field(description="One line verdict, max 80 characters.")
    summary: str = Field(description="Three or four sentences, in the requested language.")
    key_numbers: list[KeyNumber] = Field(default_factory=list, description="Numbers used, copied from FACTS.")
