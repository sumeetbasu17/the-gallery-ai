"""MCP server exposing the match-intelligence tools.

Two ways to run it:
  * mounted inside the match room service at /mcp (live match state), or
  * standalone over a replayed synthetic match, for exploring the tools from
    any MCP client (VS Code, Foundry agents, MCP Inspector):

      python -m mcp_server --seed 7 --until 70 --port 8765
"""

from __future__ import annotations

from typing import Callable

from mcp.server.mcpserver import MCPServer

from stats_engine import MatchState

from .tools import MatchTools

INSTRUCTIONS = (
    "Read-only tools over a live synthetic football match. All numbers come from a deterministic stats "
    "engine. Quote them exactly; never invent statistics. Clubs and players are fictional."
)


def create_mcp_server(state_provider: Callable[[], MatchState]) -> tuple[MCPServer, MatchTools]:
    tools = MatchTools(state_provider)
    server = MCPServer(name="the-gallery-match", title="The Gallery match intelligence",
                       instructions=INSTRUCTIONS, version="0.1.0")
    for fn in tools.all():
        server.add_tool(fn, name=fn.__name__, description=(fn.__doc__ or "").strip())
    return server, tools
