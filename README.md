# The Gallery — an AI broadcast crew for every fan

An AI football broadcast crew that turns live match events into personalised, fact-checked tactical insights, explainable overlays, and multilingual commentary using specialised agents, MCP, and Azure AI.

Built for **Inside the Game: Developer Hackathon** (Microsoft × Premier League). All clubs, players and match data are fictional and synthetic.

## One pipeline, five stages

| Stage | What happens | Built with |
|---|---|---|
| **Ingest** | Our own simulator streams football-realistic events and 1 Hz tracking frames | Python, Azure Event Hubs, Container Apps |
| **Interpret** | Deterministic stats engine: player tags, pass quality, ball/shot speed, Control vs Chaos, Pressure, Rhythm | Python, Cosmos DB, Fabric Eventhouse / ADX |
| **Explain** | Multi-agent crew reasons over match state via an MCP server; every claim is fact-checked | Microsoft Foundry, Agent Framework, MCP |
| **Render** | Timed, machine-readable overlay events drawn on a live 2D pitch with a "Why?" evidence panel | Azure Web PubSub, React |
| **Personalize** | Casual vs Analyst, favourite club, Player Cam, single metric, multilingual text and audio | Azure AI Translator, Azure AI Speech |

## Repository layout

```
packages/schema/     Shared event + overlay contracts (pydantic)
services/simulator/  Synthetic match engine (live + batch modes)
services/stats_engine/  Deterministic metrics and tactic detectors
services/mcp_server/ MCP tools the agents use to query match state
services/agents/     The agent crew (Director, Analyst, Judge, Storyteller, Fact-Checker, Fan Producer, Scenario Writer)
web/                 React + TypeScript front end
infra/               Bicep + azd infrastructure as code
docs/                Architecture and design notes
tests/               Unit and detector-accuracy tests
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Print a full synthetic match to the terminal (no tracking frames)
python -m simulator --seed 7 --no-frames

# Watch a match unfold live at 60x speed (90 minutes in ~90 seconds)
python -m simulator --seed 7 --live --speed 60 --no-frames

# Write events + 1 Hz tracking frames to JSONL
python -m simulator --seed 7 --out data/generated/match_7.jsonl

pytest
```

## The synthetic data

The simulator plays two fictional clubs, **Riverside Athletic** (4-3-3, high press) and **Northgate United** (4-2-3-1), second by second. Each team follows a timeline of tactical profiles (block height, width, press intensity, tempo). These are *planted ground truth*: for example, Northgate switch to a narrow low block at 60', and the tests prove the shift is measurable in the tracking data.

Calibrated over 10 seeds to look like top-flight football: ~1,000 passes at ~79% completion, ~23 shots, ~2 goals, realistic sprint speeds (≤ 36 km/h). Every match is deterministic for a given seed.

## Status

Work in progress. Done: shared schema, match simulator. Next: streaming, stats engine, MCP server, agents, web app.
