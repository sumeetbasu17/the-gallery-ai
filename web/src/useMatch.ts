import { useEffect, useReducer, useRef } from "react";
import type { Frame, MatchEvent, Metadata, Meters, Overlay, Recap, TeamSummary, TraceStep } from "./types";

export interface MatchState {
  connected: boolean;
  running: boolean;
  metadata: Metadata | null;
  frame: Frame | null;
  minute: number;
  score: { home: number; away: number };
  meters: Meters | null;
  teams: Record<string, TeamSummary>;
  winProb: Record<string, number> | null;
  overlays: Overlay[];
  trace: TraceStep[];
  events: MatchEvent[];
  recap: Recap | null;
  crewStats: Record<string, number>;
  languages: string[];
  scenario: { title?: string; storyline?: string } | null;
}

const initial: MatchState = {
  connected: false,
  running: false,
  metadata: null,
  frame: null,
  minute: 0,
  score: { home: 0, away: 0 },
  meters: null,
  teams: {},
  winProb: null,
  overlays: [],
  trace: [],
  events: [],
  recap: null,
  crewStats: {},
  languages: ["en"],
  scenario: null,
};

type Action =
  | { type: "connected"; value: boolean }
  | { type: "message"; msg: { type: string; data: any } }
  | { type: "reset" };

function reducer(state: MatchState, action: Action): MatchState {
  if (action.type === "connected") return { ...state, connected: action.value };
  if (action.type === "reset") return { ...initial, connected: state.connected, running: true };
  const { type, data } = action.msg;
  switch (type) {
    case "hello":
      return {
        ...state,
        running: data.status?.running ?? false,
        scenario: data.status?.scenario ?? null,
        metadata: data.metadata,
        score: data.score ?? state.score,
        minute: data.minute ?? 0,
        meters: data.meters && Object.keys(data.meters).length ? data.meters : null,
        teams: data.teams ?? {},
        overlays: data.overlays ?? [],
        recap: data.recap ?? null,
        trace: data.trace ?? [],
        crewStats: data.crew_stats ?? {},
        languages: data.languages ?? ["en"],
      };
    case "metadata":
      return { ...state, metadata: data, running: true };
    case "frame":
      return { ...state, frame: data, minute: data.minute, score: data.score };
    case "meters":
      return { ...state, meters: data.meters, teams: data.teams, winProb: data.win_probability ?? state.winProb };
    case "overlay":
      return { ...state, overlays: [...state.overlays.slice(-120), data] };
    case "trace":
      return {
        ...state,
        trace: [...state.trace.slice(-200), data],
        crewStats: {
          ...state.crewStats,
          llm_calls: (state.crewStats.llm_calls ?? 0) + (data.agent === "match_director" && data.status === "skipped" ? 0 : 1),
          errors: (state.crewStats.errors ?? 0) + (data.status === "error" ? 1 : 0),
        },
      };
    case "event":
      return { ...state, events: [...state.events.slice(-60), data], score: data.score ?? state.score };
    case "recap":
      return { ...state, recap: data };
    case "status":
      return { ...state, running: data.running, scenario: data.scenario ?? state.scenario };
    default:
      return state;
  }
}

export function useMatch() {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: number | undefined;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      wsRef.current = ws;
      ws.onopen = () => dispatch({ type: "connected", value: true });
      ws.onmessage = (e) => dispatch({ type: "message", msg: JSON.parse(e.data) });
      ws.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
    };
    connect();
    const ping = window.setInterval(() => wsRef.current?.readyState === 1 && wsRef.current.send("ping"), 20000);
    return () => {
      closed = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      wsRef.current?.close();
    };
  }, []);

  const start = async (seed: number, speed: number, source: "local" | "eventhub" = "local", brief = "") => {
    dispatch({ type: "reset" });
    await fetch("/api/match/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ seed, speed, source, brief }),
    });
  };

  return { state, start };
}
