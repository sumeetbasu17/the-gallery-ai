"""Incremental match state + detectors.

Feed it envelopes in order (`ingest`). It keeps running statistics, rolling
windows and the three signature meters, and returns `Signal`s whenever
something worth airing happens. No LLM is involved here: these numbers are the
source of truth the agents must respect.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gallery_schema.events import Envelope, EventType, MatchEvent, MatchMetadata, TrackingFrame
from gallery_schema.overlays import Evidence

from . import metrics as M
from .signals import Signal, SignalType

WINDOW_S = 300.0          # rolling window for meters (5 match-minutes)
SHAPE_WINDOW_S = 180.0    # rolling window for line height / width
SHAPE_EVAL_EVERY_S = 30.0
SHAPE_CONFIRMATIONS = 2   # consecutive evaluations before a block/width change is announced
SHAPE_BASELINE_S = 900.0  # compare the last 3 min against the 12 min before
SHAPE_COOLDOWN_S = 600.0
LINE_DELTA_M = 5.0
MOMENTUM_MIN_PASSES = 12  # final-third passes needed in the window before tilt means anything
BALL_ADJUST = 0.2       # metres of line movement per metre of ball movement
WIDTH_DELTA_M = 4.0
SIDES = ("home", "away")
DEFENSIVE_ACTIONS = {EventType.TACKLE, EventType.INTERCEPTION, EventType.FOUL}


def _other(side: str) -> str:
    return "away" if side == "home" else "home"


def _attack_x(side: str, x: float) -> float:
    """x in the attacking frame of `side` (attacking towards 105)."""
    return x if side == "home" else 105.0 - x


@dataclass
class PlayerStats:
    passes: int = 0
    completed: int = 0
    streak: int = 0
    best_streak: int = 0
    difficulty_sum: int = 0
    elite_passes: int = 0
    shots: int = 0
    on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    sprints: int = 0
    in_sprint: bool = False
    fast_s: int = 0
    last_sprint_start_s: float = -1e9
    last_sprint_signal_s: float = -1e9
    last_xy: Optional[tuple[float, float]] = None
    last_speed: float = 0.0


@dataclass
class TeamStats:
    passes: int = 0
    completed: int = 0
    shots: int = 0
    on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    possession_s: float = 0.0
    fouls: int = 0
    cards: int = 0
    tackles: int = 0
    interceptions: int = 0


@dataclass
class ShapeTracker:
    samples: deque = field(default_factory=deque)   # (second, line_m, width_m)
    block: Optional[str] = None
    width: Optional[str] = None
    pending_block_n: int = 0
    pending_width_n: int = 0
    last_block_signal: float = -1e9
    last_width_signal: float = -1e9


class MatchState:
    def __init__(self) -> None:
        self.meta: Optional[MatchMetadata] = None
        self.names: dict[str, str] = {}
        self.player_side: dict[str, str] = {}
        self.team_name: dict[str, str] = {}
        self.players: dict[str, PlayerStats] = defaultdict(PlayerStats)
        self.teams: dict[str, TeamStats] = {s: TeamStats() for s in SIDES}
        self.events: deque[MatchEvent] = deque()           # rolling WINDOW_S * 2
        self.all_events: list[MatchEvent] = []
        self.owner: Optional[str] = None
        self.owner_since: float = 0.0
        self.chain_len: int = 0
        self.chains: deque = deque()                        # (second, side, passes)
        self.shape: dict[str, ShapeTracker] = {s: ShapeTracker() for s in SIDES}
        self.last_shape_eval: float = 0.0
        self.last_press_eval: float = 0.0
        self.press_baseline: dict[str, Optional[float]] = {s: None for s in SIDES}
        self.last_press_signal: dict[str, float] = {s: -1e9 for s in SIDES}
        self.last_momentum_eval: float = 0.0
        self.last_control: Optional[float] = None
        self.last_momentum_signal: float = -1e9
        self.clock: float = 0.0
        self.minute: int = 0
        self.score = {"home": 0, "away": 0}
        self._sig_seq = 0

    # ------------------------------------------------------------ plumbing
    def _signal(self, type_: SignalType, summary: str, importance: int, side: Optional[str] = None,
                player_id: Optional[str] = None, evidence: Optional[list[Evidence]] = None) -> Signal:
        self._sig_seq += 1
        return Signal(signal_id=f"{self.meta.match_id}-S{self._sig_seq:04d}", match_id=self.meta.match_id,
                      type=type_, second=self.clock, minute=self.minute, side=side, player_id=player_id,
                      importance=importance, summary=summary, evidence=evidence or [])

    def name(self, pid: Optional[str]) -> str:
        return self.names.get(pid or "", "Unknown")

    def ingest(self, env: Envelope) -> list[Signal]:
        if env.kind == "metadata" and env.metadata:
            self._on_metadata(env.metadata)
            return []
        if env.kind == "event" and env.event:
            return self._on_event(env.event)
        if env.kind == "frame" and env.frame:
            return self._on_frame(env.frame)
        return []

    def _on_metadata(self, meta: MatchMetadata) -> None:
        self.meta = meta
        for team in (meta.home, meta.away):
            self.team_name[team.side.value] = team.name
            for p in team.players:
                self.names[p.id] = p.name
                self.player_side[p.id] = team.side.value

    # ------------------------------------------------------------- events
    def _set_owner(self, side: Optional[str], t: float) -> None:
        if side is None or side == self.owner:
            return
        if self.owner is not None:
            self.teams[self.owner].possession_s += t - self.owner_since
            self.chains.append((t, self.owner, self.chain_len))
        self.owner, self.owner_since, self.chain_len = side, t, 0

    def _on_event(self, ev: MatchEvent) -> list[Signal]:
        self.clock, self.minute = ev.second, ev.minute
        self.events.append(ev)
        self.all_events.append(ev)
        while self.events and self.events[0].second < self.clock - 2 * WINDOW_S:
            self.events.popleft()
        while self.chains and self.chains[0][0] < self.clock - 2 * WINDOW_S:
            self.chains.popleft()

        side = ev.side.value if ev.side else None
        out: list[Signal] = []
        t = ev.type

        if t in (EventType.KICK_OFF, EventType.POSSESSION_CHANGE):
            self._set_owner(side, ev.second)
        elif t in (EventType.PASS, EventType.CARRY, EventType.SHOT):
            self._set_owner(side, ev.second)

        if t == EventType.PASS and side:
            out += self._on_pass(ev, side)
        elif t == EventType.SHOT and side:
            out += self._on_shot(ev, side)
        elif t == EventType.GOAL and side:
            self.score[side] += 1
            self.teams[side].goals += 1
            self.players[ev.player_id].goals += 1
            out.append(self._signal(
                SignalType.GOAL, f"Goal for {self.team_name[side]} scored by {self.name(ev.player_id)}. "
                f"Score {self.score['home']}-{self.score['away']}.", 100, side, ev.player_id,
                [Evidence(metric="score_home", value=self.score["home"]),
                 Evidence(metric="score_away", value=self.score["away"])]))
        elif t == EventType.FOUL and side:
            self.teams[side].fouls += 1
        elif t == EventType.TACKLE and side:
            self.teams[side].tackles += 1
        elif t == EventType.INTERCEPTION and side:
            self.teams[side].interceptions += 1
        elif t == EventType.CARD and side:
            self.teams[side].cards += 1
            out.append(self._signal(SignalType.CARD, f"Yellow card for {self.name(ev.player_id)} "
                                    f"({self.team_name[side]}).", 45, side, ev.player_id))
        elif t == EventType.SUBSTITUTION and side:
            d = ev.detail or {}
            out.append(self._signal(SignalType.SUBSTITUTION, f"{self.team_name[side]} substitution: "
                                    f"{d.get('in')} on for {d.get('out')}.", 35, side, ev.player_id))
        elif t in (EventType.HALF_TIME, EventType.FULL_TIME):
            st = SignalType.HALF_TIME if t == EventType.HALF_TIME else SignalType.FULL_TIME
            out.append(self._signal(st, f"{'Half-time' if st == SignalType.HALF_TIME else 'Full-time'}: "
                                    f"{self.team_name['home']} {self.score['home']}-{self.score['away']} "
                                    f"{self.team_name['away']}.", 90))

        if self.clock - self.last_press_eval >= 60:
            self.last_press_eval = self.clock
            out += self._eval_press()
        if self.clock - self.last_momentum_eval >= 60:
            self.last_momentum_eval = self.clock
            out += self._eval_momentum()
        return out

    def _on_pass(self, ev: MatchEvent, side: str) -> list[Signal]:
        ps, ts = self.players[ev.player_id], self.teams[side]
        diff = M.pass_difficulty(ev)
        ps.passes += 1
        ts.passes += 1
        ps.difficulty_sum += diff
        ok = ev.outcome == "success"
        out: list[Signal] = []
        if ok:
            ps.completed += 1
            ts.completed += 1
            ps.streak += 1
            self.chain_len += 1
            if ps.streak > ps.best_streak:
                ps.best_streak = ps.streak
            if ps.streak in (15, 25, 40):
                out.append(self._signal(
                    SignalType.PASS_STREAK, f"{self.name(ev.player_id)} has completed {ps.streak} passes in a row.",
                    40 + ps.streak // 2, side, ev.player_id,
                    [Evidence(metric="consecutive_completed_passes", value=ps.streak)]))
            if diff >= 70:
                ps.elite_passes += 1
                comps = M.difficulty_components(ev)
                out.append(self._signal(
                    SignalType.ELITE_PASS,
                    f"{self.name(ev.player_id)} completed a pass rated {diff}/100 for difficulty to "
                    f"{self.name(ev.target_player_id)}: {comps['distance_m']:.0f} m, "
                    f"{int(comps['lines_broken'])} defenders bypassed"
                    f"{', under pressure' if ev.under_pressure else ''}.",
                    55 + (diff - 70), side, ev.player_id,
                    [Evidence(metric="pass_difficulty", value=diff),
                     Evidence(metric="pass_distance_m", value=comps["distance_m"]),
                     Evidence(metric="lines_broken", value=comps["lines_broken"]),
                     Evidence(metric="ball_speed_kmh", value=ev.ball_speed_kmh or 0)]))
        else:
            ps.streak = 0
        return out

    def _on_shot(self, ev: MatchEvent, side: str) -> list[Signal]:
        ps, ts = self.players[ev.player_id], self.teams[side]
        xg = ev.xg or 0.0
        ps.shots += 1
        ps.xg += xg
        ts.shots += 1
        ts.xg += xg
        if ev.outcome in ("on_target", "saved", "goal"):
            ts.on_target += 1
            ps.on_target += 1
        out: list[Signal] = []
        speed = ev.ball_speed_kmh or 0.0
        ev_list = [Evidence(metric="xg", value=round(xg, 2)), Evidence(metric="shot_speed_kmh", value=speed),
                   Evidence(metric="distance_m", value=float((ev.detail or {}).get("distance_m", 0)))]
        if xg >= 0.25 and ev.outcome != "goal":
            out.append(self._signal(SignalType.BIG_CHANCE, f"Big chance for {self.name(ev.player_id)} "
                                    f"(xG {xg:.2f}), outcome: {ev.outcome}.", 70, side, ev.player_id, ev_list))
        if speed >= M.POWER_SHOT_KMH:
            out.append(self._signal(SignalType.POWER_SHOT, f"Shot by {self.name(ev.player_id)} struck at "
                                    f"{speed:.0f} km/h, outcome: {ev.outcome}.", 50, side, ev.player_id, ev_list))
        return out

    # ------------------------------------------------------------- frames
    def _on_frame(self, fr: TrackingFrame) -> list[Signal]:
        self.clock = fr.second
        out: list[Signal] = []
        by_side: dict[str, list] = {"home": [], "away": []}
        for p in fr.players:
            side = self.player_side.get(p.player_id)
            if side is None:
                continue
            ps = self.players[p.player_id]
            if ps.last_xy is not None:
                step = ((p.x - ps.last_xy[0]) ** 2 + (p.y - ps.last_xy[1]) ** 2) ** 0.5
                if step < 12:  # ignore substitutions / teleports
                    ps.distance_m += step
            ps.last_xy = (p.x, p.y)
            new_best = p.speed_kmh > ps.top_speed_kmh + 0.5
            if p.speed_kmh > ps.top_speed_kmh:
                ps.top_speed_kmh = p.speed_kmh
            # a sprint is a run above SPRINT_KMH; it ends only once the player eases off (hysteresis),
            # so noise around the threshold is not counted as dozens of sprints
            ps.fast_s = ps.fast_s + 1 if p.speed_kmh >= M.SPRINT_KMH else 0
            if ps.in_sprint and p.speed_kmh < M.SPRINT_END_KMH:
                ps.in_sprint = False
            elif not ps.in_sprint and ps.fast_s >= M.SPRINT_MIN_S and fr.second - ps.last_sprint_start_s >= 8:
                ps.in_sprint = True
                ps.last_sprint_start_s = fr.second
                ps.sprints += 1
            ps.last_speed = p.speed_kmh
            if p.speed_kmh >= M.TOP_SPEED_TAG_KMH and new_best and fr.second - ps.last_sprint_signal_s > 900:
                ps.last_sprint_signal_s = fr.second
                out.append(self._signal(
                    SignalType.SPRINT, f"{self.name(p.player_id)} hit {p.speed_kmh:.1f} km/h, his fastest of the match.", 30, side,
                    p.player_id, [Evidence(metric="speed_kmh", value=p.speed_kmh),
                                  Evidence(metric="distance_covered_km", value=round(ps.distance_m / 1000, 2))]))
            if not self._is_keeper(p.player_id):
                by_side[side].append(p)

        # shape of the side *out of* possession
        if self.owner in SIDES:
            defending = _other(self.owner)
            pts = by_side[defending]
            if len(pts) >= 8:
                depths = sorted(_attack_x(defending, p.x) for p in pts)
                # ball-adjusted line height: a line naturally follows the ball up and down the pitch
                ball_x = _attack_x(defending, fr.ball.x)
                line = statistics.mean(depths[:4]) - BALL_ADJUST * (ball_x - 52.5)
                ys = [p.y for p in pts]
                width = max(ys) - min(ys)
                sh = self.shape[defending]
                sh.samples.append((fr.second, line, width))
                while sh.samples and sh.samples[0][0] < fr.second - SHAPE_BASELINE_S:
                    sh.samples.popleft()

        if fr.second - self.last_shape_eval >= SHAPE_EVAL_EVERY_S:
            self.last_shape_eval = fr.second
            for side in SIDES:
                out += self._eval_shape(side)
        return out

    def _is_keeper(self, pid: str) -> bool:
        if not self.meta:
            return False
        for team in (self.meta.home, self.meta.away):
            for p in team.players:
                if p.id == pid:
                    return p.position == "GK"
        return False

    def _eval_shape(self, side: str) -> list[Signal]:
        """Compare the last 3 minutes of shape with the 12 minutes before.

        A shift is announced when the defensive line moves >= LINE_DELTA_M (or the
        width moves >= WIDTH_DELTA_M) and the change holds for two evaluations.
        """
        sh = self.shape[side]
        now = self.clock
        recent = [s for s in sh.samples if s[0] >= now - SHAPE_WINDOW_S]
        before = [s for s in sh.samples if now - SHAPE_BASELINE_S <= s[0] < now - SHAPE_WINDOW_S]
        if len(recent) < 40 or len(before) < 120:
            return []
        line, width = statistics.mean(s[1] for s in recent), statistics.mean(s[2] for s in recent)
        b_line, b_width = statistics.mean(s[1] for s in before), statistics.mean(s[2] for s in before)
        if sh.block is None:
            sh.block, sh.width = M.classify_block(b_line), M.classify_width(b_width)
        out: list[Signal] = []
        team = self.team_name[side]
        window = f"last {int(SHAPE_WINDOW_S // 60)} min vs previous {int((SHAPE_BASELINE_S - SHAPE_WINDOW_S) // 60)}"

        if abs(line - b_line) >= LINE_DELTA_M and now - sh.last_block_signal > SHAPE_COOLDOWN_S:
            sh.pending_block_n += 1
            if sh.pending_block_n >= SHAPE_CONFIRMATIONS:
                prev, block = sh.block, M.classify_block(line)
                sh.block, sh.pending_block_n, sh.last_block_signal = block, 0, now
                direction = "dropped deeper" if line < b_line else "pushed higher"
                change = f"{prev} block to {block} block" if prev != block else f"still a {block} block"
                out.append(self._signal(
                    SignalType.BLOCK_SHIFT,
                    f"{team} have {direction} out of possession ({change}). Defensive line now "
                    f"{line:.1f} m from own goal, was {b_line:.1f} m.",
                    80 if block == "low" else 65, side, None,
                    [Evidence(metric="defensive_line_m", value=round(line, 1), baseline=round(b_line, 1),
                              window=window, source_tool="team_shape"),
                     Evidence(metric="team_width_m", value=round(width, 1), baseline=round(b_width, 1),
                              window=window, source_tool="team_shape")]))
        else:
            sh.pending_block_n = 0

        if abs(width - b_width) >= WIDTH_DELTA_M and now - sh.last_width_signal > SHAPE_COOLDOWN_S:
            sh.pending_width_n += 1
            if sh.pending_width_n >= SHAPE_CONFIRMATIONS:
                prev_w, wcls = sh.width, M.classify_width(width)
                sh.width, sh.pending_width_n, sh.last_width_signal = wcls, 0, now
                verb = "narrowed" if width < b_width else "widened"
                out.append(self._signal(
                    SignalType.WIDTH_SHIFT,
                    f"{team} have {verb} their shape out of possession "
                    f"({f'{prev_w} to {wcls}' if prev_w != wcls else f'still {wcls}'}): "
                    f"width {width:.1f} m, was {b_width:.1f} m.", 60, side, None,
                    [Evidence(metric="team_width_m", value=round(width, 1), baseline=round(b_width, 1),
                              window=window, source_tool="team_shape")]))
        else:
            sh.pending_width_n = 0
        return out

    # ------------------------------------------------------- press + meters
    def ppda(self, side: str, window_s: float = 600.0) -> Optional[float]:
        """Opponent passes in their own 60% of the pitch per defensive action by `side` in that zone."""
        opp = _other(side)
        lo = self.clock - window_s
        passes = actions = 0
        for e in self.all_events_since(lo):
            if e.start is None or e.side is None:
                continue
            if e.type == EventType.PASS and e.side.value == opp and _attack_x(opp, e.start.x) < 63:
                passes += 1
            elif e.type in DEFENSIVE_ACTIONS and e.side.value == side and _attack_x(side, e.start.x) > 42:
                actions += 1
        if passes < 25:
            return None
        return round(passes / max(actions, 1), 1)

    def all_events_since(self, second: float) -> list[MatchEvent]:
        out = []
        for e in reversed(self.all_events):
            if e.second < second:
                break
            out.append(e)
        return out[::-1]

    def _eval_press(self) -> list[Signal]:
        out: list[Signal] = []
        for side in SIDES:
            current = self.ppda(side, 600)
            if current is None:
                continue
            base = self.press_baseline[side]
            if base is None:
                self.press_baseline[side] = current
                continue
            ratio = current / base if base else 1.0
            if (ratio >= 1.8 or ratio <= 0.55) and self.clock - self.last_press_signal[side] > 900:
                self.last_press_signal[side] = self.clock
                eased = ratio >= 1.8  # higher PPDA = less pressing
                out.append(self._signal(
                    SignalType.PRESS_SHIFT,
                    f"{self.team_name[side]} are pressing {'less' if eased else 'more'} intensely: PPDA "
                    f"{current} over the last 10 minutes (was {base}). Lower PPDA means more pressing.",
                    60, side, None,
                    [Evidence(metric="ppda", value=current, baseline=base, window="last 10 min",
                              source_tool="pressure_meter")]))
                self.press_baseline[side] = current
            else:
                # slowly track the baseline so gradual drift does not fire
                self.press_baseline[side] = round(0.85 * base + 0.15 * current, 1)
        return out

    def meters(self, window_s: float = WINDOW_S) -> dict:
        """The three signature meters over the rolling window."""
        evs = self.all_events_since(self.clock - window_s)
        mins = max(window_s / 60.0, 1.0)
        passes = {s: 0 for s in SIDES}
        completed = {s: 0 for s in SIDES}
        final_third = {s: 0 for s in SIDES}
        pressured = turnovers = long_balls = 0
        pressure_acts = {s: 0 for s in SIDES}
        for e in evs:
            s = e.side.value if e.side else None
            if e.type == EventType.PASS and s:
                passes[s] += 1
                completed[s] += e.outcome == "success"
                if e.end is not None and _attack_x(s, e.end.x) > 70:
                    final_third[s] += 1
                pressured += e.under_pressure
                long_balls += bool((e.detail or {}).get("lofted"))
            elif e.type == EventType.POSSESSION_CHANGE:
                turnovers += 1
            if s and e.type in (EventType.PRESSURE, EventType.TACKLE, EventType.INTERCEPTION):
                pressure_acts[s] += 1
        total_passes = max(sum(passes.values()), 1)
        chains = [c[2] for c in self.chains if c[0] >= self.clock - window_s]
        avg_chain = statistics.mean(chains) if chains else 0.0

        # Control vs chaos: 0 = chaos, 100 = control
        turnover_rate = turnovers / mins                     # ~2-4 per minute in normal play
        pressured_share = pressured / total_passes
        long_share = long_balls / total_passes
        chaos = min(100.0, 18 * turnover_rate + 60 * pressured_share + 60 * long_share)
        control = round(100 - chaos)
        tilt_total = max(final_third["home"] + final_third["away"], 1)
        dominant = max(SIDES, key=lambda s: passes[s] + 2 * final_third[s])

        return {
            "window_minutes": round(mins, 1),
            "control_vs_chaos": {
                "control": control,
                "label": "controlled" if control >= 60 else "chaotic" if control < 40 else "contested",
                "in_control": self.team_name.get(dominant, dominant) if control >= 40 else None,
                "turnovers_per_min": round(turnover_rate, 2),
                "passes_under_pressure_pct": round(100 * pressured_share, 1),
                "long_ball_pct": round(100 * long_share, 1),
                "avg_passes_per_possession": round(avg_chain, 1),
                "possession_pct": {self.team_name.get(s, s): round(100 * passes[s] / total_passes) for s in SIDES},
                "field_tilt_pct": {self.team_name.get(s, s): round(100 * final_third[s] / tilt_total)
                                   for s in SIDES},
            },
            "pressure": {
                self.team_name.get(s, s): {
                    "pressing_actions_per_min": round(pressure_acts[s] / mins, 1),
                    "ppda_10min": self.ppda(s, 600),
                } for s in SIDES
            },
            "rhythm": {
                "passes_per_min": round(sum(passes.values()) / mins, 1),
                "label": ("high tempo" if sum(passes.values()) / mins > 13
                          else "slow" if sum(passes.values()) / mins < 9 else "steady"),
                "completion_pct": {self.team_name.get(s, s): round(100 * completed[s] / max(passes[s], 1))
                                   for s in SIDES},
            },
        }

    def _eval_momentum(self) -> list[Signal]:
        if self.clock < 600 or self.clock - self.last_momentum_signal < 600:
            return []
        m = self.meters()
        tilt = m["control_vs_chaos"]["field_tilt_pct"]
        home_share = tilt.get(self.team_name["home"], 50)
        out: list[Signal] = []
        ft_passes = sum(1 for e in self.all_events_since(self.clock - WINDOW_S)
                        if e.type == EventType.PASS and e.side and e.end is not None
                        and _attack_x(e.side.value, e.end.x) > 70)
        if ft_passes < MOMENTUM_MIN_PASSES:
            return out
        if self.last_control is not None and abs(home_share - self.last_control) >= 30:
            gaining = "home" if home_share > self.last_control else "away"
            self.last_momentum_signal = self.clock
            out.append(self._signal(
                SignalType.MOMENTUM_SWING,
                f"Momentum swing towards {self.team_name[gaining]}: their share of final-third passes moved "
                f"from {self.last_control if gaining == 'home' else 100 - self.last_control:.0f}% to "
                f"{home_share if gaining == 'home' else 100 - home_share:.0f}% over the last 5 minutes.",
                65, gaining, None,
                [Evidence(metric="field_tilt_pct", value=home_share if gaining == "home" else 100 - home_share,
                          baseline=self.last_control if gaining == "home" else 100 - self.last_control,
                          window="last 5 min", source_tool="control_meter")]))
        self.last_control = home_share
        return out

    # ------------------------------------------------------------ snapshots
    def player_summary(self, pid: str) -> dict:
        ps = self.players[pid]
        return {
            "player": self.name(pid), "team": self.team_name.get(self.player_side.get(pid, ""), ""),
            "passes": ps.passes, "pass_completion_pct": round(100 * ps.completed / ps.passes) if ps.passes else None,
            "avg_pass_difficulty": round(ps.difficulty_sum / ps.passes) if ps.passes else None,
            "elite_passes": ps.elite_passes, "best_pass_streak": ps.best_streak,
            "shots": ps.shots, "shots_on_target": ps.on_target, "xg": round(ps.xg, 2), "goals": ps.goals,
            "distance_km": round(ps.distance_m / 1000, 2), "top_speed_kmh": round(ps.top_speed_kmh, 1),
            "sprints": ps.sprints,
        }

    def team_summary(self) -> dict:
        total_pos = sum(t.possession_s for t in self.teams.values()) or 1
        return {
            self.team_name.get(s, s): {
                "goals": t.goals, "shots": t.shots, "on_target": t.on_target, "xg": round(t.xg, 2),
                "passes": t.passes, "pass_completion_pct": round(100 * t.completed / t.passes) if t.passes else None,
                "possession_pct": round(100 * t.possession_s / total_pos), "fouls": t.fouls, "cards": t.cards,
                "tackles": t.tackles, "interceptions": t.interceptions,
                "block": self.shape[s].block, "width": self.shape[s].width,
            } for s, t in self.teams.items()
        }
