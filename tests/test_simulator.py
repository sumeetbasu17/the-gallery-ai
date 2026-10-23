"""Realism and ground-truth tests for the synthetic match simulator."""

import statistics

import pytest

from gallery_schema.events import Side
from simulator import MatchSimulator, northgate_united, riverside_athletic


def _run(seed: int, frames: bool = False):
    return MatchSimulator(riverside_athletic(), northgate_united(), seed=seed).run(with_frames=frames)


@pytest.fixture(scope="module")
def matches():
    return [_run(s) for s in range(1, 11)]


def test_is_deterministic():
    a, b = _run(42), _run(42)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]


def test_event_counts_look_like_top_flight_football(matches):
    passes = [sum(e.type.value == "pass" for e in m.events) for m in matches]
    shots = [sum(e.type.value == "shot" for e in m.events) for m in matches]
    goals = [sum(e.type.value == "goal" for e in m.events) for m in matches]
    completion = [
        sum(e.outcome == "success" for e in m.events if e.type.value == "pass")
        / sum(e.type.value == "pass" for e in m.events)
        for m in matches
    ]
    assert 800 <= statistics.mean(passes) <= 1200
    assert 0.74 <= statistics.mean(completion) <= 0.88
    assert 16 <= statistics.mean(shots) <= 32
    assert 1.0 <= statistics.mean(goals) <= 4.0


def test_events_are_time_ordered_and_bounded(matches):
    for m in matches:
        seconds = [e.second for e in m.events]
        assert seconds == sorted(seconds)
        assert m.events[-1].type.value == "full_time"
        assert 90 * 60 <= seconds[-1] <= 104 * 60


def test_max_three_subs_per_team(matches):
    for m in matches:
        for side in Side:
            subs = [e for e in m.events if e.type.value == "substitution" and e.side == side]
            assert len(subs) <= 3


def test_planted_low_block_is_visible_in_tracking():
    """Northgate switch to a low block at 60'. Their out-of-possession outfield
    line should sit much closer to their own goal (x=105 for the away side)."""
    m = _run(3, frames=True)
    ngu = {p.id for p in m.metadata.away.players if p.position != "GK"}
    poss = sorted((e.second, e.side) for e in m.events
                  if e.type.value in ("kick_off", "possession_change") and e.side)

    def defending_depth(lo: int, hi: int) -> float:
        depths = []
        for f in m.frames:
            minute = f.second / 60
            if not (lo <= minute < hi):
                continue
            owner = max((p for p in poss if p[0] <= f.second), default=(0, None))[1]
            if owner != Side.HOME:
                continue
            xs = [105 - p.x for p in f.players if p.player_id in ngu]  # distance from own goal
            depths.append(statistics.mean(xs))
        return statistics.mean(depths)

    before, after = defending_depth(20, 55), defending_depth(65, 88)
    assert after < before - 5, (before, after)


def test_speeds_are_human(matches):
    m = _run(1, frames=True)
    top = max(p.speed_kmh for f in m.frames for p in f.players)
    assert top <= 37


def test_scenarios_drive_the_simulator_and_produce_labels():
    from simulator.scenarios import ground_truth, random_scenario, teams_from_scenario

    home, away = teams_from_scenario(random_scenario(123))
    assert home.tactics[0].from_minute == 0 and away.tactics[0].from_minute == 0
    labels = ground_truth(home, away)
    assert all(lbl["minute"] >= 10 for lbl in labels)
    match = MatchSimulator(home, away, seed=123).run(with_frames=False)
    assert match.events[-1].type.value == "full_time"


def test_bad_scenario_input_is_sanitised():
    from simulator.scenarios import teams_from_scenario

    home, _ = teams_from_scenario({"home": {"formation": "2-3-5", "plan": [
        {"from_minute": 50, "block": "ultra", "width": "x", "press_intensity": 9}]}})
    assert home.formation == "4-3-3"
    assert home.tactics[0].from_minute == 0
    assert home.tactics[1].block == "mid" and home.tactics[1].press_intensity == 1.0
