"""Stats engine tests: detector accuracy against the simulator's planted ground truth."""

import pytest

from gallery_schema.events import EventType, MatchEvent, Point, Side
from simulator import MatchSimulator, northgate_united, riverside_athletic
from stats_engine import MatchState, SignalType, pass_difficulty

SEEDS = range(1, 9)

# Ground truth from clubs.py: Northgate switch to a narrow low block at 60',
# Riverside drop from a high, wide block to a mid, balanced block at 75'.
PLANTED = [("away", 60), ("home", 75)]
DETECTION_WINDOW_MIN = 6


def _replay(seed: int):
    match = MatchSimulator(riverside_athletic(), northgate_united(), seed=seed).run()
    state, signals = MatchState(), []
    for env in match.envelopes():
        signals += state.ingest(env)
    return state, signals


@pytest.fixture(scope="module")
def replays():
    return {s: _replay(s) for s in SEEDS}


def test_planted_block_shifts_are_detected_quickly(replays):
    for seed, (_, signals) in replays.items():
        shifts = [s for s in signals if s.type == SignalType.BLOCK_SHIFT]
        for side, minute in PLANTED:
            hits = [s for s in shifts if s.side == side and minute <= s.minute <= minute + DETECTION_WINDOW_MIN]
            assert hits, f"seed {seed}: missed {side} shift at {minute}'"
            assert "dropped deeper" in hits[0].summary


def test_no_false_shape_alarms(replays):
    for seed, (_, signals) in replays.items():
        for s in signals:
            if s.type not in (SignalType.BLOCK_SHIFT, SignalType.WIDTH_SHIFT):
                continue
            ok = any(s.side == side and minute <= s.minute <= minute + DETECTION_WINDOW_MIN
                     for side, minute in PLANTED)
            assert ok, f"seed {seed}: false alarm {s.minute}' {s.summary}"


def test_low_block_and_narrow_shape_are_labelled(replays):
    state, signals = replays[1]
    assert state.shape["away"].block == "low"
    assert state.shape["away"].width == "narrow"
    assert state.shape["home"].block == "mid"


def test_signals_carry_evidence(replays):
    _, signals = replays[1]
    for s in signals:
        if s.type in (SignalType.BLOCK_SHIFT, SignalType.ELITE_PASS, SignalType.PRESS_SHIFT):
            assert s.evidence, s


def test_goal_signals_match_final_score(replays):
    for seed, (state, signals) in replays.items():
        goals = [s for s in signals if s.type == SignalType.GOAL]
        assert len(goals) == state.score["home"] + state.score["away"]


def test_signal_volume_is_broadcastable(replays):
    """Roughly one candidate insight per minute or less: the Director needs room to choose."""
    for seed, (_, signals) in replays.items():
        assert len(signals) <= 120, (seed, len(signals))
        assert sum(s.type == SignalType.SPRINT for s in signals) <= 20


def test_meters_are_well_formed(replays):
    state, _ = replays[1]
    m = state.meters()
    assert 0 <= m["control_vs_chaos"]["control"] <= 100
    assert set(m["pressure"]) == {"Riverside Athletic", "Northgate United"}
    assert m["rhythm"]["passes_per_min"] > 0


def _pass(distance, pressure=False, lines=0, lofted=False, end_x=50.0):
    return MatchEvent(event_id="e", match_id="m", seq=1, type=EventType.PASS, minute=1, second=1.0,
                      side=Side.HOME, start=Point(x=40, y=34), end=Point(x=end_x, y=34),
                      under_pressure=pressure, outcome="success",
                      detail={"distance_m": distance, "lines_broken": lines, "lofted": lofted})


def test_pass_difficulty_orders_sensibly():
    easy = pass_difficulty(_pass(8))
    long_ = pass_difficulty(_pass(35, lofted=True))
    hard = pass_difficulty(_pass(35, pressure=True, lines=4, lofted=True, end_x=95))
    assert easy < 10 < long_ < hard <= 100
