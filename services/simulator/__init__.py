"""Synthetic football match simulator for The Gallery."""

from .clubs import northgate_united, riverside_athletic
from .engine import MatchSimulator, SimulatedMatch

__all__ = ["MatchSimulator", "SimulatedMatch", "riverside_athletic", "northgate_united"]
