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

## The stats engine (no AI, the source of truth)

`services/stats_engine` replays the stream incrementally and produces **signals**: facts with evidence that the agents may phrase but never alter.

- **Player tags:** distance covered, top speed, sprint count; a tag fires when a player sets a new match-best above 33 km/h.
- **Pass quality:** distance, completion, and a 0-100 **difficulty rating** built from distance, pressure, defenders bypassed, loft and target zone.
- **Speed metrics:** ball speed per pass, shot speed, power-shot alerts.
- **Three signature meters** over a rolling 5 minutes: **Control vs Chaos** (turnovers, passes under pressure, long balls, possession chains), **Pressure** (pressing actions, PPDA), **Rhythm** (passes per minute, completion).
- **Tactical detectors:** ball-adjusted defensive line height and team width (last 3 min vs the 12 before), pressing changes (PPDA), momentum swings (field tilt).

**Measured against planted ground truth across 8 matches:** every planted tactical change is detected within 1-2 match-minutes, with zero false shape alarms (`tests/test_stats_engine.py`).

## The MCP server

`services/mcp_server` exposes read-only match tools over the Model Context Protocol: `get_match_snapshot`, `get_meters`, `get_team_shape`, `get_player_summary`, `list_players`, `get_recent_events`, `get_top_performers`, `win_probability` and `explain_term` (the Jargon Decoder). Agents can only see the match through these tools, so every number they quote is traceable.

```bash
python -m mcp_server --seed 7 --until 70 --port 8765   # explore with any MCP client
```

## The agent crew (Microsoft Agent Framework + Foundry)

| Agent | Role |
|---|---|
| **Match Director** | Decides what airs: air budget, cooldowns, LLM tie-break when moments compete |
| **Tactical Analyst** | Investigates a signal with MCP tools and explains the mechanism |
| **Moment Judge** | Rates importance from win probability, score and minute (runs in parallel with the Analyst) |
| **Storyteller** | Writes the on-screen line from verified facts |
| **Fact-Checker** | Deterministic check of every number, name and direction, plus an LLM semantic check; rejects and sends back for a rewrite |
| **Fan Producer** | Casual, analyst, home-fan and away-fan versions in every language |
| **Recap Writer** | Full-time recap (or a recap of a match the producer ended early), fact-checked like everything else |
| **Translator** | The recap in every language |
| **Pundit** | Answers viewers' live questions from MCP tool results; the question is treated as untrusted input |
| **Coach Analyst** | Half-time report per club: what works, what doesn't, three changes, every point backed by a number |
| **Scenario Writer** | Turns a one-line storyline into a synthetic match |

Quick data tags (top speed, shot speed, pass difficulty, cards) skip the LLM entirely. If a model call fails or a story fails fact-checking twice, deterministic templates keep the broadcast running, and the overlay is marked unverified. Every overlay carries its agent trace for the Producer view.

```bash
python -m agents --seed 7 --offline            # no Azure needed (scripted client)
python -m agents --seed 7 --until 66           # live models in your Foundry project (az login + .env)
```

## Run the whole experience locally

```bash
# terminal 1: the match room (API + WebSocket + MCP), from the repo root
cd services && uvicorn match_room.app:app --port 8000

# terminal 2: the web app
cd web && npm install && npm run dev        # open http://localhost:5173
```

If port 8000 is taken, run the API on another port and point the web app at it: `uvicorn match_room.app:app --port 8001` and `npm run dev:8001`.

Pick a seed and a speed, press **Kick off**, and switch between **Casual / Analyst**, a club lens, **Player cam**, a single-meter **Focus**, and **English / हिन्दी / Español**. Then:

- **Show me** on any insight replays that moment on the pitch, with the analyst's evidence (for example the old and new defensive line) drawn on the grass.
- **3D camera** tilts the pitch into a broadcast angle; with Player cam on, the camera follows that player with a live stat card beside them.
- **Ask the pundit** a question in your language; **Listen** reads the answer aloud.
- **Commentary voice** reads each new insight aloud (Azure AI Speech when configured, the browser voice otherwise).
- **Pause / Resume / End match** are producer controls. At half-time play holds while the **Coach** reports are written, like a real broadcast break. Ending early still produces a recap.
- **Recap** has the match story chart, the audio recap in every language and an auto-generated **highlights reel**: the goals and biggest tactical shifts, replayed and narrated.
- **Matches** lists every finished or stopped match (newest 50, paginated). Open one to read its insights, coach reports and recap and replay any moment. Frames are not stored: the simulator is deterministic, so the seed rebuilds them.
- **Producer** shows the crew's handoffs live, with rejections and recoveries.

Set `GALLERY_ANALYST_VIA_MCP=1` to make the Analyst call the live `/mcp` endpoint over real MCP. The archive uses Cosmos DB when `COSMOS_ENDPOINT` is set and local JSON files in `.gallery-data/` otherwise.

## Synthetic data at scale

```bash
python -m simulator.dataset --matches 50 --out data/generated/dataset --frames
```

Every match gets a random tactical scenario, and the output includes `labels.jsonl` with the planted ground truth, `matches.csv` summaries and per-match `events.jsonl` / `frames.jsonl`, ready for a Microsoft Fabric Lakehouse or any dataframe. The **Scenario Writer** agent does the same from a one-line storyline typed on the kick-off screen.

## Evaluation

`python scripts/evaluate.py --matches 20` replays matches with random tactical scenarios the detectors were never tuned on and scores them against the planted ground truth; add `--crew` to also score the agents (fact-check pass rate, fallbacks, latency per agent). Latest results: [docs/evaluation.md](docs/evaluation.md).

## Status

Done: schema, simulator, stats engine, MCP server, agent crew, match room service, web app (live view, replays, 3D camera, pundit, coach, recap with highlights, archive), Azure infrastructure, Scenario Writer, dataset generator, evaluation harness.
