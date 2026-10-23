"""Match-intelligence tools exposed over MCP (and in-process for tests).

Every tool reads from the deterministic `MatchState`. Agents can only see the
match through these tools, so every number they quote has a traceable source.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable, Optional

from gallery_schema.events import EventType

from stats_engine import MatchState

from .glossary import lookup

_SIDE_ALIASES = {"home": "home", "away": "away"}


class MatchTools:
    """A thin, read-only facade over a live MatchState."""

    def __init__(self, state_provider: Callable[[], MatchState]):
        self._state = state_provider

    # -- helpers -----------------------------------------------------------
    @property
    def s(self) -> MatchState:
        return self._state()

    def _side(self, team: str) -> Optional[str]:
        t = team.strip().lower()
        if t in _SIDE_ALIASES:
            return _SIDE_ALIASES[t]
        for side, name in self.s.team_name.items():
            if t in name.lower():
                return side
        return None

    def _player_id(self, player: str) -> Optional[str]:
        p = player.strip().lower()
        if p in {k.lower() for k in self.s.names}:
            return next(k for k in self.s.names if k.lower() == p)
        for pid, name in self.s.names.items():
            if p == name.lower() or p in name.lower():
                return pid
        return None

    # -- tools -------------------------------------------------------------
    def get_match_snapshot(self) -> dict[str, Any]:
        """Current minute, score, and full-match team totals (shots, xG, passes, possession, shape)."""
        s = self.s
        return {
            "minute": s.minute,
            "score": {s.team_name.get("home"): s.score["home"], s.team_name.get("away"): s.score["away"]},
            "teams": s.team_summary(),
        }

    def get_meters(self, window_minutes: int = 5) -> dict[str, Any]:
        """The three signature meters (Control vs Chaos, Pressure, Rhythm) over the last N minutes (1-15)."""
        window = max(1, min(15, int(window_minutes)))
        return self.s.meters(window * 60.0)

    def get_team_shape(self, team: str, window_minutes: int = 3) -> dict[str, Any]:
        """Out-of-possession defensive line height and width for a team ('home', 'away' or a team name),
        for the last N minutes compared with the 12 minutes before."""
        side = self._side(team)
        if side is None:
            return {"error": f"Unknown team '{team}'. Use 'home', 'away' or a team name."}
        sh = self.s.shape[side]
        now = self.s.clock
        win = max(1, min(10, int(window_minutes))) * 60
        recent = [x for x in sh.samples if x[0] >= now - win]
        before = [x for x in sh.samples if x[0] < now - win]

        def summarise(rows):
            if not rows:
                return None
            return {"defensive_line_m": round(statistics.mean(r[1] for r in rows), 1),
                    "width_m": round(statistics.mean(r[2] for r in rows), 1), "samples": len(rows)}

        return {"team": self.s.team_name[side], "current_block": sh.block, "current_width": sh.width,
                "recent": summarise(recent), "previous": summarise(before),
                "note": "Defensive line = ball-adjusted distance of the deepest four outfielders from own goal."}

    def get_player_summary(self, player: str) -> dict[str, Any]:
        """Full-match stats for one player (by name or id): passes, completion, pass difficulty, shots, xG,
        distance covered, top speed, sprints."""
        pid = self._player_id(player)
        if pid is None:
            return {"error": f"Unknown player '{player}'. Call list_players first."}
        return self.s.player_summary(pid)

    def list_players(self, team: str = "") -> list[dict[str, Any]]:
        """Squad list with ids, names, numbers and positions; optionally filtered to one team."""
        s, out = self.s, []
        if s.meta is None:
            return out
        side = self._side(team) if team else None
        for t in (s.meta.home, s.meta.away):
            if side and t.side.value != side:
                continue
            for p in t.players:
                out.append({"id": p.id, "name": p.name, "number": p.number, "position": p.position,
                            "team": t.name})
        return out

    def get_recent_events(self, minutes: int = 3, event_type: str = "") -> list[dict[str, Any]]:
        """Key events in the last N minutes (max 10). Optional filter: shot, goal, card, substitution,
        tackle, interception, foul. Passes and carries are omitted to keep this short."""
        s = self.s
        minutes = max(1, min(10, int(minutes)))
        keep = {EventType.SHOT, EventType.GOAL, EventType.CARD, EventType.SUBSTITUTION, EventType.TACKLE,
                EventType.INTERCEPTION, EventType.FOUL}
        out = []
        for e in s.all_events_since(s.clock - minutes * 60):
            if e.type not in keep or (event_type and e.type.value != event_type):
                continue
            row = {"minute": e.minute, "type": e.type.value, "team": s.team_name.get(e.side.value, "") if e.side
                   else "", "player": s.name(e.player_id)}
            if e.outcome:
                row["outcome"] = e.outcome
            if e.xg is not None:
                row["xg"] = e.xg
            if e.ball_speed_kmh is not None and e.type == EventType.SHOT:
                row["shot_speed_kmh"] = e.ball_speed_kmh
            out.append(row)
        return out[-25:]

    def get_top_performers(self, metric: str = "pass_difficulty", limit: int = 3) -> list[dict[str, Any]]:
        """Leaders for a metric: pass_difficulty, distance, top_speed, xg, elite_passes, pass_streak."""
        s = self.s
        keymap = {
            "pass_difficulty": lambda p: (p.difficulty_sum / p.passes) if p.passes >= 10 else -1,
            "distance": lambda p: p.distance_m, "top_speed": lambda p: p.top_speed_kmh,
            "xg": lambda p: p.xg, "elite_passes": lambda p: p.elite_passes, "pass_streak": lambda p: p.best_streak,
        }
        if metric not in keymap:
            return [{"error": f"metric must be one of {sorted(keymap)}"}]
        ranked = sorted(s.players.items(), key=lambda kv: keymap[metric](kv[1]), reverse=True)
        return [s.player_summary(pid) for pid, _ in ranked[: max(1, min(5, int(limit)))]]

    def win_probability(self) -> dict[str, Any]:
        """Simple live win/draw/loss probabilities from score, time left and xG balance."""
        s = self.s
        return win_probability(s.score["home"], s.score["away"], s.minute,
                               s.teams["home"].xg, s.teams["away"].xg, s.team_name)

    def explain_term(self, term: str) -> dict[str, Any]:
        """Jargon Decoder: plain-English definition of a football term and how this system measures it."""
        hit = lookup(term)
        return hit or {"error": f"No glossary entry for '{term}'."}

    def all(self) -> list[Callable[..., Any]]:
        return [self.get_match_snapshot, self.get_meters, self.get_team_shape, self.get_player_summary,
                self.list_players, self.get_recent_events, self.get_top_performers, self.win_probability,
                self.explain_term]


def win_probability(home_goals: int, away_goals: int, minute: int, home_xg: float, away_xg: float,
                    names: dict[str, str]) -> dict[str, Any]:
    """Poisson model of remaining goals; scoring rates blend a league prior with this match's xG rate."""
    import math

    remaining = max(0.0, 90 - minute) / 90.0
    played = max(minute, 10) / 90.0
    prior = 1.35
    lam_h = remaining * (0.6 * prior + 0.4 * home_xg / played)
    lam_a = remaining * (0.6 * prior + 0.4 * away_xg / played)

    def pmf(k, lam):
        return math.exp(-lam) * lam ** k / math.factorial(k)

    hw = dr = aw = 0.0
    for i in range(8):
        for j in range(8):
            p = pmf(i, lam_h) * pmf(j, lam_a)
            diff = (home_goals + i) - (away_goals + j)
            if diff > 0:
                hw += p
            elif diff == 0:
                dr += p
            else:
                aw += p
    total = hw + dr + aw or 1.0
    return {names.get("home", "home"): round(100 * hw / total), "draw": round(100 * dr / total),
            names.get("away", "away"): round(100 * aw / total), "minute": minute}
