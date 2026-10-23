"""Jargon Decoder: plain-English definitions of the terms commentators use.

Each entry links to the live metric that illustrates it, so the UI can show the
term *in this match's own numbers*.
"""

GLOSSARY: dict[str, dict[str, str]] = {
    "low block": {
        "definition": "Defending deep, close to your own penalty area, with the lines compact. You give up "
                      "space and the ball higher up the pitch to protect the area behind you.",
        "metric": "defensive_line_m",
        "how_we_measure": "Average distance of the four deepest outfield players from their own goal when "
                          "out of possession, adjusted for where the ball is. Under 25 m counts as a low block.",
    },
    "mid block": {
        "definition": "Defending from around the halfway line: letting centre-backs have the ball but closing "
                      "down the midfield.",
        "metric": "defensive_line_m",
        "how_we_measure": "Defensive line between 25 m and 36 m from own goal.",
    },
    "high block": {
        "definition": "Defending high up the pitch, pushing the back line up to squeeze space and win the ball "
                      "back near the opponent's goal.",
        "metric": "defensive_line_m",
        "how_we_measure": "Defensive line 36 m or more from own goal.",
    },
    "parking the bus": {
        "definition": "Slang for an extreme low block: nearly everyone behind the ball, protecting a result.",
        "metric": "defensive_line_m",
        "how_we_measure": "A low block combined with a narrow shape and very little pressing.",
    },
    "playing narrow": {
        "definition": "Players squeezed into the centre of the pitch, protecting the middle and leaving the "
                      "flanks open.",
        "metric": "team_width_m",
        "how_we_measure": "Out-of-possession width (widest to narrowest outfielder) under 30 m.",
    },
    "playing wide": {
        "definition": "Stretching the pitch, using the touchlines to pull the opponent's shape apart.",
        "metric": "team_width_m",
        "how_we_measure": "Width of 38 m or more.",
    },
    "pressing": {
        "definition": "Closing down the player on the ball to force a mistake or win it back quickly.",
        "metric": "ppda",
        "how_we_measure": "PPDA: opponent passes allowed in their own 60% of the pitch for each defensive action "
                          "there. Lower PPDA means more intense pressing.",
    },
    "ppda": {
        "definition": "Passes Per Defensive Action. A standard measure of pressing intensity.",
        "metric": "ppda",
        "how_we_measure": "Opponent passes in their own 60% of the pitch divided by your tackles, interceptions "
                          "and fouls in that zone. Lower = more pressing.",
    },
    "xg": {
        "definition": "Expected goals: the chance a shot becomes a goal, judged from where and how it was taken.",
        "metric": "xg",
        "how_we_measure": "A model of distance and shooting angle; a penalty is about 0.76, a long shot about 0.03.",
    },
    "field tilt": {
        "definition": "Which team is spending more time in the opponent's final third.",
        "metric": "field_tilt_pct",
        "how_we_measure": "Share of all final-third passes made by each team.",
    },
    "control vs chaos": {
        "definition": "Whether the game is calm and structured or broken and end-to-end.",
        "metric": "control",
        "how_we_measure": "Built from turnovers per minute, passes under pressure and long balls. 100 is total "
                          "control, 0 is chaos.",
    },
    "tempo": {
        "definition": "How quickly the ball is moving: a high-tempo game has rapid passing and few pauses.",
        "metric": "passes_per_min",
        "how_we_measure": "Passes per minute across both teams over the last 5 minutes.",
    },
    "line-breaking pass": {
        "definition": "A pass that travels past one or more lines of defenders, cutting the opposition open.",
        "metric": "lines_broken",
        "how_we_measure": "Number of opposition outfielders the pass travels past.",
    },
    "transition": {
        "definition": "The moment possession changes hands, when both teams are briefly out of shape.",
        "metric": "turnovers_per_min",
        "how_we_measure": "Possession changes per minute.",
    },
}


def lookup(term: str) -> dict | None:
    key = term.strip().lower()
    if key in GLOSSARY:
        return {"term": key, **GLOSSARY[key]}
    for k, v in GLOSSARY.items():
        if key in k or k in key:
            return {"term": k, **v}
    return None


def find_terms(text: str) -> list[str]:
    low = text.lower()
    return [k for k in GLOSSARY if k in low]
