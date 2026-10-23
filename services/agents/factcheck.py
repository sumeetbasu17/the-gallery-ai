"""Deterministic fact-checking: numbers, names and directions must match the evidence.

This runs on every story before it can reach the screen. An optional LLM pass
(see crew.py) adds a semantic check for tactical moments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
_MINUTE = re.compile(r"\b(\d{1,3})(?:'|’|st|nd|rd|th|\s?min)")
_NAME = re.compile(r"\b([A-Z][a-zà-ÿ]+(?:-[A-Z][a-zà-ÿ]+)?) ([A-Z][a-zà-ÿ]+(?:-[A-Z][a-zà-ÿ]+)?)\b")
FREE_NUMBERS = {0.0, 1.0, 2.0, 3.0, 90.0, 100.0}

DIRECTION_RULES = {
    # signal summary phrase -> phrases that would contradict it
    "dropped deeper": ["pushed higher", "pushed up", "higher line", "pressing higher"],
    "pushed higher": ["dropped deeper", "sitting deeper", "dropped back"],
    "narrowed": ["widened", "stretched wider"],
    "widened": ["narrowed", "squeezed narrow"],
    "pressing less": ["pressing more", "pressing harder", "more intense press"],
    "pressing more": ["pressing less", "easing off", "eased off"],
}


@dataclass
class CheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def _numbers_in(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        out |= {float(n) for n in _NUM.findall(obj)}
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out |= _numbers_in(k) | _numbers_in(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            out |= _numbers_in(v)
    elif hasattr(obj, "model_dump"):
        out |= _numbers_in(obj.model_dump())
    return out


def allowed_numbers(*sources: Any) -> set[float]:
    """All numbers in the sources, plus rounded forms and simple differences people quote."""
    base: set[float] = set()
    for s in sources:
        base |= _numbers_in(s)
    expanded = set(base)
    for v in base:
        expanded |= {round(v), round(v, 1), float(int(v))}
    return expanded


def _matches(value: float, allowed: Iterable[float]) -> bool:
    for a in allowed:
        if abs(value - a) <= max(0.051, 0.006 * abs(a)):
            return True
    return False


def check_story(text: str, allowed: set[float], roster: set[str], signal_summary: str = "",
                extra_names: Iterable[str] = ()) -> CheckResult:
    problems: list[str] = []

    minutes = {float(m) for m in _MINUTE.findall(text)}
    for raw in _NUM.findall(text):
        v = float(raw)
        if v in FREE_NUMBERS or v in minutes or _matches(v, allowed):
            continue
        problems.append(f"The number {raw} is not in the evidence.")

    known = set(roster) | set(extra_names)
    surnames = {n.split(" ", 1)[-1] for n in roster}
    firsts = {n.split(" ", 1)[0] for n in roster}
    for first, last in _NAME.findall(text):
        full = f"{first} {last}"
        if full in known:
            continue
        if last in surnames or first in firsts:
            problems.append(f"'{full}' is not a player in this match.")

    low_text, low_sum = text.lower(), signal_summary.lower()
    for phrase, contradictions in DIRECTION_RULES.items():
        if phrase in low_sum:
            for c in contradictions:
                if c in low_text:
                    problems.append(f"The story says '{c}' but the evidence says '{phrase}'.")

    return CheckResult(ok=not problems, problems=problems)
