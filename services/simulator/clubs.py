"""Fictional clubs, squads and default tactical plans.

Every name here is invented. Nothing refers to a real club or player.
"""

from __future__ import annotations

from gallery_schema.events import Player, Side, TacticalProfile, Team

# (number, name, position) — eleven starters followed by the bench
_RIVERSIDE = [
    (1, "Tomas Brandt", "GK"), (2, "Kofi Mensah-Lowe", "RB"), (4, "Elias Varga", "CB"),
    (5, "Daniel Okoro", "CB"), (3, "Rafael Duarte", "LB"), (6, "Jonah Whitfield", "DM"),
    (8, "Mateo Ferrante", "CM"), (10, "Aarav Sen", "CM"), (7, "Luca Moretti", "RW"),
    (9, "Isaac Ndiaye", "ST"), (11, "Felix Holm", "LW"),
    (14, "Sami Haddad", "CM"), (17, "Ola Berg", "RW"), (19, "Marcus Adeyemi", "ST"),
]

_NORTHGATE = [
    (1, "Piotr Zielinski-Ray", "GK"), (2, "Callum Reyes", "RB"), (5, "Hugo Lindqvist", "CB"),
    (6, "Bastien Morel", "CB"), (3, "Yusuf Arslan", "LB"), (4, "Theo Kamara", "DM"),
    (8, "Nikolai Petrov", "DM"), (7, "Diego Salcedo", "RW"), (10, "Kenji Watanabe", "AM"),
    (11, "Omar Haidari", "LW"), (9, "Rhys Calloway", "ST"),
    (16, "Liam Achterberg", "DM"), (18, "Ade Okonkwo", "RW"), (20, "Bruno Castell", "ST"),
]


def _squad(prefix: str, side: Side, rows) -> list[Player]:
    return [
        Player(id=f"{prefix}{num}", name=name, number=num, position=pos, side=side)
        for num, name, pos in rows
    ]


def riverside_athletic() -> Team:
    return Team(
        id="RVA", name="Riverside Athletic", short_name="Riverside", side=Side.HOME,
        formation="4-3-3", players=_squad("RVA", Side.HOME, _RIVERSIDE),
        tactics=[
            TacticalProfile(from_minute=0, block="high", width="wide", press_intensity=0.75, tempo=0.65),
            TacticalProfile(from_minute=75, block="mid", width="balanced", press_intensity=0.45, tempo=0.5),
        ],
    )


def northgate_united() -> Team:
    return Team(
        id="NGU", name="Northgate United", short_name="Northgate", side=Side.AWAY,
        formation="4-2-3-1", players=_squad("NGU", Side.AWAY, _NORTHGATE),
        tactics=[
            TacticalProfile(from_minute=0, block="mid", width="balanced", press_intensity=0.6, tempo=0.55),
            # Planted ground truth: Northgate drop into a narrow low block after the hour.
            TacticalProfile(from_minute=60, block="low", width="narrow", press_intensity=0.2, tempo=0.35),
        ],
    )
