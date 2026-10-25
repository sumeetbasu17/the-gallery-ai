"""Synthetic match engine.

Plays a 90-minute match between two fictional teams and produces:
  * on-ball events (passes, carries, shots, tackles, pressure, fouls, ...)
  * 1 Hz tracking frames for all 22 players and the ball

Team behaviour follows each team's TacticalProfile timeline (block height,
width, press intensity, tempo). Because the tactics are known, they serve as
ground truth for testing the stats engine's detectors.

Geometry is computed in each team's *attacking frame* (attacking towards
x = 105) and converted to absolute pitch coordinates, where the home team
attacks towards x = 105.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Optional

import numpy as np

from gallery_schema.events import (
    PITCH_LENGTH as L,
    PITCH_WIDTH as W,
    Envelope,
    EventType,
    MatchEvent,
    MatchMetadata,
    Player,
    PlayerFrame,
    Point,
    Side,
    TacticalProfile,
    Team,
    TrackingFrame,
)

from .formations import FORMATIONS

GOAL_WIDTH = 7.32
MAX_RUN_MS = 9.0  # ~32 km/h top sprint speed

_BLOCK_LINE_OUT = {"high": 40.0, "mid": 30.0, "low": 18.0}
_BLOCK_SPAN_OUT = {"high": 42.0, "mid": 38.0, "low": 30.0}
_BLOCK_LINE_IN = {"high": 46.0, "mid": 38.0, "low": 32.0}
_WIDTH_IN = {"wide": 0.95, "balanced": 0.82, "narrow": 0.66}
_WIDTH_OUT = {"wide": 0.75, "balanced": 0.66, "narrow": 0.5}
_PRESS_ZONE_START = {"high": 12.0, "mid": 40.0, "low": 66.0}  # attacker-frame x


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class _TeamState:
    team: Team
    on_pitch: list[Player]
    bench: list[Player]
    anchors: dict[str, tuple[float, float]]
    subs_made: int = 0
    goals: int = 0

    @property
    def side(self) -> Side:
        return self.team.side


@dataclass
class SimulatedMatch:
    metadata: MatchMetadata
    events: list[MatchEvent] = field(default_factory=list)
    frames: list[TrackingFrame] = field(default_factory=list)

    def envelopes(self) -> Iterator[Envelope]:
        """Metadata, then events and frames merged in time order."""
        yield Envelope(kind="metadata", metadata=self.metadata)
        ei = fi = 0
        while ei < len(self.events) or fi < len(self.frames):
            take_event = fi >= len(self.frames) or (
                ei < len(self.events) and self.events[ei].second <= self.frames[fi].second
            )
            if take_event:
                yield Envelope(kind="event", event=self.events[ei])
                ei += 1
            else:
                yield Envelope(kind="frame", frame=self.frames[fi])
                fi += 1


class MatchSimulator:
    def __init__(self, home: Team, away: Team, seed: int = 7, match_id: Optional[str] = None,
                 venue: str = "Harbourside Stadium"):
        self.rng = np.random.default_rng(seed)
        self.match_id = match_id or f"M{seed:05d}"
        self.metadata = MatchMetadata(match_id=self.match_id, venue=venue, home=home, away=away, seed=seed)
        self.teams = {Side.HOME: self._init_team(home), Side.AWAY: self._init_team(away)}
        self.events: list[MatchEvent] = []
        self._seq = 0
        # possession timeline for frame generation: (second, side)
        self._possession: list[tuple[float, Side]] = []

    # ------------------------------------------------------------------ setup
    def _init_team(self, team: Team) -> _TeamState:
        starters, bench = team.players[:11], team.players[11:]
        anchors = {p.id: a for p, a in zip(starters, FORMATIONS[team.formation])}
        return _TeamState(team=team, on_pitch=list(starters), bench=list(bench), anchors=anchors)

    @staticmethod
    def tactic(team: Team, minute: int) -> TacticalProfile:
        current = team.tactics[0]
        for t in team.tactics:
            if t.from_minute <= minute:
                current = t
        return current

    # --------------------------------------------------------------- geometry
    @staticmethod
    def to_abs(side: Side, x: float, y: float) -> tuple[float, float]:
        return (x, y) if side == Side.HOME else (L - x, W - y)

    to_frame = to_abs  # the mirror transform is its own inverse

    def target_positions(self, side: Side, minute: int, in_possession: bool,
                         ball_abs: tuple[float, float]) -> dict[str, tuple[float, float]]:
        """Where each player of `side` wants to be, in absolute coordinates."""
        ts = self.teams[side]
        tac = self.tactic(ts.team, minute)
        bx, by = self.to_frame(side, *ball_abs)
        if in_possession:
            line, span = _BLOCK_LINE_IN[tac.block], 62.0
            w, y_shift, x_shift = _WIDTH_IN[tac.width], 0.1, 0.38
        else:
            line, span = _BLOCK_LINE_OUT[tac.block], _BLOCK_SPAN_OUT[tac.block]
            w, y_shift, x_shift = _WIDTH_OUT[tac.width], 0.3, 0.2
        out: dict[str, tuple[float, float]] = {}
        for p in ts.on_pitch:
            ax, ay = ts.anchors[p.id]
            if p.position == "GK":
                fx, fy = (10.0 if in_possession else 5.0), W / 2 + 0.1 * (by - W / 2)
            else:
                fx = line + (ax - 0.27) * span + x_shift * (bx - L / 2)
                fy = W / 2 + (ay - 0.5) * W * w + y_shift * (by - W / 2)
            out[p.id] = self.to_abs(side, _clamp(fx, 2, L - 2), _clamp(fy, 1, W - 1))
        return out

    def _nearest(self, side: Side, minute: int, in_possession: bool, ball_abs, exclude=()) -> Player:
        pos = self.target_positions(side, minute, in_possession, ball_abs)
        cands = [p for p in self.teams[side].on_pitch if p.id not in exclude and p.position != "GK"]
        return min(cands, key=lambda p: math.dist(pos[p.id], ball_abs))

    # ----------------------------------------------------------------- events
    def _emit(self, etype: EventType, second: float, minute: int, side: Optional[Side] = None,
              **kw) -> MatchEvent:
        self._seq += 1
        ev = MatchEvent(event_id=f"{self.match_id}-{self._seq:05d}", match_id=self.match_id, seq=self._seq,
                        type=etype, minute=minute, second=round(second, 2), side=side, **kw)
        self.events.append(ev)
        return ev

    @staticmethod
    def _pt(xy) -> Point:
        return Point(x=round(_clamp(xy[0], 0, L), 2), y=round(_clamp(xy[1], 0, W), 2))

    @staticmethod
    def _xg(fx: float, fy: float) -> float:
        dx, dy = L - fx, abs(fy - W / 2)
        dist = math.hypot(dx, dy)
        angle = math.atan2(GOAL_WIDTH * dx, dx * dx + dy * dy - (GOAL_WIDTH / 2) ** 2)
        if angle < 0:
            angle += math.pi
        z = -1.0 + 1.6 * angle - 0.09 * dist
        return round(_clamp(1 / (1 + math.exp(-z)), 0.01, 0.85), 3)

    def _maybe_sub(self, side: Side, clock: float, minute: int) -> None:
        ts = self.teams[side]
        if not ts.bench or ts.subs_made >= 3 or minute < 58:
            return
        if self.rng.random() > 0.004:
            return
        incoming = ts.bench.pop(0)
        same = [p for p in ts.on_pitch if p.position == incoming.position and p.position != "GK"]
        outgoing = same[0] if same else ts.on_pitch[-1]
        ts.anchors[incoming.id] = ts.anchors[outgoing.id]
        ts.on_pitch[ts.on_pitch.index(outgoing)] = incoming
        ts.subs_made += 1
        self._subs.append((clock, side, incoming, outgoing))
        self._emit(EventType.SUBSTITUTION, clock, minute, side, player_id=incoming.id,
                   target_player_id=outgoing.id, detail={"in": incoming.name, "out": outgoing.name})

    def _play_half(self, half: int, start_clock: float, kickoff_side: Side) -> float:
        rng = self.rng
        base_minute = 0 if half == 1 else 45
        added = int(rng.integers(1, 5)) if half == 1 else int(rng.integers(3, 7))
        end_clock = start_clock + (45 + added) * 60

        side = kickoff_side
        ball = (L / 2, W / 2)
        carrier = self._nearest(side, base_minute, True, ball)
        clock = start_clock
        self._emit(EventType.KICK_OFF, clock, base_minute, side, player_id=carrier.id,
                   start=self._pt(ball), detail={"half": half})
        self._possession.append((clock, side))

        def display_minute(c: float) -> tuple[int, int]:
            m = base_minute + int((c - start_clock) // 60)
            cap = base_minute + 45
            return (min(m, cap), max(0, m - cap))

        def turnover(new_side: Side, at: tuple[float, float], c: float) -> None:
            nonlocal side, ball, carrier
            side, ball = new_side, at
            m, _ = display_minute(c)
            carrier = self._nearest(side, m, True, ball)
            self._possession.append((c, side))

        while clock < end_clock:
            minute, added_now = display_minute(clock)
            att, dfn = self.teams[side], self.teams[Side.AWAY if side == Side.HOME else Side.HOME]
            tac_a, tac_d = self.tactic(att.team, minute), self.tactic(dfn.team, minute)
            fx, fy = self.to_frame(side, *ball)
            extra = {"added_minute": added_now} if added_now else {}

            self._maybe_sub(Side.HOME, clock, minute)
            self._maybe_sub(Side.AWAY, clock, minute)
            if carrier not in att.on_pitch:
                carrier = self._nearest(side, minute, True, ball)

            # --- pressure from the defending side
            press_p = 0.06
            if fx >= _PRESS_ZONE_START[tac_d.block]:
                press_p = 0.12 + 0.5 * tac_d.press_intensity
            under_p = rng.random() < press_p
            presser = None
            if under_p:
                presser = self._nearest(dfn.side, minute, False, ball)
                self._emit(EventType.PRESSURE, clock, minute, dfn.side, player_id=presser.id,
                           target_player_id=carrier.id, start=self._pt(ball), detail=extra)
                clock += 0.6
                if rng.random() < 0.035:  # foul
                    self._emit(EventType.FOUL, clock, minute, dfn.side, player_id=presser.id,
                               target_player_id=carrier.id, start=self._pt(ball), detail=extra)
                    if rng.random() < 0.18:
                        self._emit(EventType.CARD, clock, minute, dfn.side, player_id=presser.id,
                                   detail={"card": "yellow", **extra})
                    clock += float(rng.uniform(15, 35))
                    continue

            dist_goal = math.hypot(L - fx, W / 2 - fy)
            shot_zone = fx > 76 and abs(fy - W / 2) < 22
            shot_p = (0.14 + 0.45 * (fx - 76) / 29) if shot_zone else 0.0
            if dist_goal < 25 and fx > 75:
                shot_p = max(shot_p, 0.06)

            if rng.random() < shot_p:
                xg = self._xg(fx, fy)
                if under_p:
                    xg = round(xg * 0.7, 3)
                roll = rng.random()
                if roll < xg:
                    outcome = "goal"
                elif roll < xg + 0.28:
                    outcome = "saved"
                elif roll < xg + 0.48:
                    outcome = "blocked"
                else:
                    outcome = "off_target"
                speed = round(float(_clamp(118 - 1.4 * dist_goal + rng.normal(0, 9), 55, 130)), 1)
                goal_end = self.to_abs(side, L, W / 2 + float(rng.uniform(-3, 3)))
                self._emit(EventType.SHOT, clock, minute, side, player_id=carrier.id, start=self._pt(ball),
                           end=self._pt(goal_end), outcome=outcome, xg=xg, ball_speed_kmh=speed,
                           under_pressure=under_p, detail={"distance_m": round(dist_goal, 1), **extra})
                clock += 1.5
                other = dfn.side
                if outcome == "goal":
                    att.goals += 1
                    self._emit(EventType.GOAL, clock, minute, side, player_id=carrier.id,
                               detail={"score": {"home": self.teams[Side.HOME].goals,
                                                 "away": self.teams[Side.AWAY].goals}, **extra})
                    clock += float(rng.uniform(45, 70))
                    turnover(other, (L / 2, W / 2), clock)
                    self._emit(EventType.KICK_OFF, clock, minute, other, player_id=carrier.id,
                               start=self._pt(ball))
                elif outcome == "saved":
                    gk = next(p for p in dfn.on_pitch if p.position == "GK")
                    turnover(other, self.to_abs(other, 6, W / 2), clock + 3)
                    carrier = gk
                    self._emit(EventType.POSSESSION_CHANGE, clock + 3, minute, other, player_id=gk.id,
                               start=self._pt(ball), detail={"reason": "save", **extra})
                    clock += float(rng.uniform(6, 14))
                else:
                    clock += float(rng.uniform(12, 25))
                    turnover(other, self.to_abs(other, 6, W / 2), clock)
                    self._emit(EventType.POSSESSION_CHANGE, clock, minute, other, player_id=carrier.id,
                               start=self._pt(ball), detail={"reason": "goal_kick" if outcome == "off_target"
                                                             else "recovery", **extra})
                continue

            # --- carry
            if rng.random() < 0.16:
                nfx = _clamp(fx + float(rng.uniform(3, 12)) * (0.6 + tac_a.tempo), 2, L - 2)
                nfy = _clamp(fy + float(rng.normal(0, 4)), 1, W - 1)
                end = self.to_abs(side, nfx, nfy)
                dur = float(rng.uniform(2, 4))
                if under_p and rng.random() < 0.3:
                    tackler = presser or self._nearest(dfn.side, minute, False, ball)
                    self._emit(EventType.CARRY, clock, minute, side, player_id=carrier.id, start=self._pt(ball),
                               end=self._pt(end), outcome="fail", under_pressure=True, detail=extra)
                    self._emit(EventType.TACKLE, clock + dur * 0.6, minute, dfn.side, player_id=tackler.id,
                               target_player_id=carrier.id, start=self._pt(end), outcome="success", detail=extra)
                    turnover(dfn.side, end, clock + dur * 0.6)
                    carrier = tackler
                    self._emit(EventType.POSSESSION_CHANGE, clock + dur * 0.6, minute, dfn.side,
                               player_id=tackler.id, start=self._pt(end), detail={"reason": "tackle", **extra})
                else:
                    self._emit(EventType.CARRY, clock, minute, side, player_id=carrier.id, start=self._pt(ball),
                               end=self._pt(end), outcome="success", under_pressure=under_p,
                               detail={"distance_m": round(math.dist(ball, end), 1), **extra})
                    ball = end
                clock += dur
                continue

            # --- pass
            positions = self.target_positions(side, minute, True, ball)
            opp_pos = self.target_positions(dfn.side, minute, False, ball)
            options, weights = [], []
            for p in att.on_pitch:
                if p.id == carrier.id or (p.position == "GK" and fx > 35):
                    continue
                tx, ty = self.to_frame(side, *positions[p.id])
                d = math.hypot(tx - fx, ty - fy)
                if d < 4:
                    continue
                progress = tx - fx
                w = math.exp(-((d - 16) ** 2) / (2 * 11 ** 2)) + (0.15 if under_p and d > 30 else 0)
                w *= 1 + tac_a.tempo * max(0.0, progress) / 15
                w *= 0.6 if progress < -5 else 1.0
                options.append((p, tx, ty, d))
                weights.append(w)
            probs = np.array(weights) / sum(weights)
            p, tx, ty = options[int(rng.choice(len(options), p=probs))][:3]
            tx = _clamp(tx + float(rng.normal(0, 1.5)), 1, L - 1)
            ty = _clamp(ty + float(rng.normal(0, 1.5)), 1, W - 1)
            d = math.hypot(tx - fx, ty - fy)
            lines_broken = sum(
                1 for q in dfn.on_pitch
                if q.position != "GK" and fx < self.to_frame(side, *opp_pos[q.id])[0] < tx
            )
            success_p = (0.985 - 0.0080 * max(0.0, d - 12) - (0.11 if under_p else 0.0)
                         - 0.10 * max(0.0, (tx - 70) / 35) - 0.03 * lines_broken
                         - 0.04 * tac_d.press_intensity)
            success_p = _clamp(success_p, 0.25, 0.98)
            end = self.to_abs(side, tx, ty)
            speed = round(float(_clamp(28 + 1.3 * d + rng.normal(0, 5), 18, 105)), 1)
            ok = rng.random() < success_p
            pass_detail = {"distance_m": round(d, 1), "lofted": d > 32, "lines_broken": lines_broken, **extra}
            self._emit(EventType.PASS, clock, minute, side, player_id=carrier.id, target_player_id=p.id,
                       start=self._pt(ball), end=self._pt(end), outcome="success" if ok else "fail",
                       ball_speed_kmh=speed, under_pressure=under_p, detail=pass_detail)
            flight = d / (speed / 3.6)
            dwell = float(rng.exponential(2.0 * (1.25 - tac_a.tempo)))
            if ok:
                ball, carrier = end, p
                clock += flight + 0.8 + dwell
                continue
            # failed pass: out of play or intercepted
            clock += flight
            if rng.random() < 0.3:
                out_y = 0.5 if ty < W / 2 else W - 0.5
                restart = self.to_abs(side, tx, out_y)
                clock += float(rng.uniform(8, 18))
                turnover(dfn.side, restart, clock)
                self._emit(EventType.POSSESSION_CHANGE, clock, minute, dfn.side, player_id=carrier.id,
                           start=self._pt(ball), detail={"reason": "throw_in", **extra})
            else:
                interceptor = self._nearest(dfn.side, minute, False, end)
                self._emit(EventType.INTERCEPTION, clock, minute, dfn.side, player_id=interceptor.id,
                           start=self._pt(end), outcome="success", detail=extra)
                turnover(dfn.side, end, clock)
                carrier = interceptor
                self._emit(EventType.POSSESSION_CHANGE, clock, minute, dfn.side, player_id=interceptor.id,
                           start=self._pt(end), detail={"reason": "interception", **extra})
                clock += 0.8

        final_minute = base_minute + 45
        end_clock = max(end_clock, self.events[-1].second + 1.0)  # whistle after the last action
        etype = EventType.HALF_TIME if half == 1 else EventType.FULL_TIME
        self._emit(etype, end_clock, final_minute, detail={
            "added_minutes": added,
            "score": {"home": self.teams[Side.HOME].goals, "away": self.teams[Side.AWAY].goals}})
        return end_clock

    # ----------------------------------------------------------------- frames
    def _ball_keyframes(self) -> list[tuple[float, tuple[float, float]]]:
        keys: list[tuple[float, tuple[float, float]]] = []
        for ev in self.events:
            if ev.start is not None:
                keys.append((ev.second, (ev.start.x, ev.start.y)))
            if ev.end is not None and ev.type in (EventType.PASS, EventType.CARRY, EventType.SHOT):
                speed = (ev.ball_speed_kmh or 12) / 3.6
                dt = math.dist((ev.start.x, ev.start.y), (ev.end.x, ev.end.y)) / max(speed, 1.0)
                keys.append((ev.second + dt, (ev.end.x, ev.end.y)))
        keys.sort(key=lambda k: k[0])
        return keys

    def _build_frames(self, total_seconds: float) -> list[TrackingFrame]:
        keys = self._ball_keyframes()
        poss = sorted(self._possession)
        minutes = {int(ev.second): ev.minute for ev in self.events}
        current = {
            side: self.target_positions(side, 0, side == Side.HOME, (L / 2, W / 2)) for side in Side
        }
        frames: list[TrackingFrame] = []
        ki = pi = 0
        minute = 0
        # Replay the line-ups through time: frames must show who was actually on the pitch at each second.
        final = {side: list(self.teams[side].on_pitch) for side in Side}
        for side in Side:
            self.teams[side].on_pitch = list(self._starters[side])
        subs = sorted(self._subs, key=lambda s: s[0])
        si = 0
        for t in range(0, int(total_seconds) + 1):
            while si < len(subs) and subs[si][0] <= t:
                _, sub_side, incoming, outgoing = subs[si]
                lineup = self.teams[sub_side].on_pitch
                lineup[lineup.index(outgoing)] = incoming
                current[sub_side][incoming.id] = current[sub_side].pop(outgoing.id, (L / 2, 0.0))
                si += 1
            while ki + 1 < len(keys) and keys[ki + 1][0] <= t:
                ki += 1
            while pi + 1 < len(poss) and poss[pi + 1][0] <= t:
                pi += 1
            minute = minutes.get(t, minute)
            (t0, b0) = keys[ki]
            if ki + 1 < len(keys):
                t1, b1 = keys[ki + 1]
                a = 0.0 if t1 == t0 else _clamp((t - t0) / (t1 - t0), 0, 1)
                ball = (b0[0] + a * (b1[0] - b0[0]), b0[1] + a * (b1[1] - b0[1]))
            else:
                ball = b0
            in_poss = poss[pi][1]
            players: list[PlayerFrame] = []
            for side in Side:
                targets = self.target_positions(side, minute, side == in_poss, ball)
                # the two nearest outfielders converge on the ball (receiving / pressing)
                keepers = {p.id for p in self.teams[side].on_pitch if p.position == "GK"}
                chasers = sorted((pid for pid in targets if pid not in keepers),
                                 key=lambda pid: math.dist(targets[pid], ball))[:2]
                for pid, tgt in targets.items():
                    if pid in chasers:
                        tgt = (0.5 * tgt[0] + 0.5 * ball[0], 0.5 * tgt[1] + 0.5 * ball[1])
                    prev = current[side].get(pid, tgt)
                    dx, dy = tgt[0] - prev[0], tgt[1] - prev[1]
                    step = math.hypot(dx, dy)
                    cap = MAX_RUN_MS * float(self.rng.uniform(0.85, 1.0))
                    if step > cap:
                        dx, dy = dx * cap / step, dy * cap / step
                    jitter = self.rng.normal(0, 0.15, 2)
                    nxt = (_clamp(prev[0] + dx + jitter[0], 0, L), _clamp(prev[1] + dy + jitter[1], 0, W))
                    speed = math.dist(prev, nxt) * 3.6
                    current[side][pid] = nxt
                    players.append(PlayerFrame(player_id=pid, x=round(nxt[0], 2), y=round(nxt[1], 2),
                                               speed_kmh=round(speed, 1)))
            frames.append(TrackingFrame(match_id=self.match_id, second=float(t),
                                        ball=self._pt(ball), players=players))
        for side in Side:
            self.teams[side].on_pitch = final[side]
        return frames

    # -------------------------------------------------------------------- run
    def run(self, with_frames: bool = True) -> SimulatedMatch:
        self._starters = {side: list(self.teams[side].on_pitch) for side in Side}
        self._subs: list = []
        first_kick = Side.HOME if self.rng.random() < 0.5 else Side.AWAY
        second_kick = Side.AWAY if first_kick == Side.HOME else Side.HOME
        ht = self._play_half(1, 0.0, first_kick)
        ft = self._play_half(2, ht, second_kick)
        frames = self._build_frames(ft) if with_frames else []
        return SimulatedMatch(metadata=self.metadata, events=self.events, frames=frames)
