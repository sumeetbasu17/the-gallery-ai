"""Deterministic templates used when a model is unavailable or its output fails checks.

The broadcast must never go blank: if every model call fails, these keep the
graphics flowing with plain, verified facts.
"""

from __future__ import annotations

from stats_engine import Signal, SignalType

from .contracts import FanVersions, Story

HEADLINES = {
    SignalType.GOAL: "GOAL!",
    SignalType.BIG_CHANCE: "Big chance",
    SignalType.POWER_SHOT: "Thunderbolt",
    SignalType.SPRINT: "Top speed",
    SignalType.ELITE_PASS: "Pass of the match contender",
    SignalType.PASS_STREAK: "Metronome",
    SignalType.BLOCK_SHIFT: "Tactical shift",
    SignalType.WIDTH_SHIFT: "Shape change",
    SignalType.PRESS_SHIFT: "Pressing change",
    SignalType.MOMENTUM_SWING: "Momentum swing",
    SignalType.CARD: "Booking",
    SignalType.SUBSTITUTION: "Substitution",
    SignalType.HALF_TIME: "Half-time",
    SignalType.FULL_TIME: "Full-time",
}


def story(signal: Signal) -> Story:
    return Story(headline=HEADLINES.get(signal.type, "Match insight"), body=signal.summary)


def fan_versions(st: Story) -> FanVersions:
    return FanVersions(casual_headline=st.headline, casual_body=st.body, analyst_headline=st.headline,
                       analyst_body=st.body, home_fans=st.body, away_fans=st.body)
