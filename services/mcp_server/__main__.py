"""Standalone MCP server over a replayed synthetic match."""

from __future__ import annotations

import argparse

from simulator import MatchSimulator, northgate_united, riverside_athletic
from stats_engine import MatchState

from .server import create_mcp_server


def main() -> None:
    ap = argparse.ArgumentParser(prog="mcp_server")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--until", type=int, default=90, help="replay the match up to this minute")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    state = MatchState()
    match = MatchSimulator(riverside_athletic(), northgate_united(), seed=args.seed).run()
    for env in match.envelopes():
        t = env.event.second if env.event else env.frame.second if env.frame else 0
        if t > args.until * 60:
            break
        state.ingest(env)

    server, _ = create_mcp_server(lambda: state)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", port=args.port)


if __name__ == "__main__":
    main()
