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

## Status

Work in progress. See `docs/` for the architecture.
