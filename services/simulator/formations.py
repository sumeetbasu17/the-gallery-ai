"""Formation anchors in the attacking frame.

Each anchor is (depth, width) in 0..1: depth 0 = own goal line, 1 = opponent's
goal line; width 0 = right touchline, 1 = left touchline (as the team attacks).
The order matches the starting eleven in clubs.py.
"""

FORMATIONS: dict[str, list[tuple[float, float]]] = {
    "4-3-3": [
        (0.05, 0.50),                                         # GK
        (0.30, 0.12), (0.25, 0.38), (0.25, 0.62), (0.30, 0.88),  # RB CB CB LB
        (0.42, 0.50), (0.53, 0.30), (0.53, 0.70),               # DM CM CM
        (0.74, 0.12), (0.82, 0.50), (0.74, 0.88),               # RW ST LW
    ],
    "4-2-3-1": [
        (0.05, 0.50),
        (0.30, 0.12), (0.25, 0.38), (0.25, 0.62), (0.30, 0.88),
        (0.42, 0.38), (0.42, 0.62),                             # DM DM
        (0.66, 0.14), (0.66, 0.50), (0.66, 0.86),               # RW AM LW
        (0.82, 0.50),                                           # ST
    ],
}
