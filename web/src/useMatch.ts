import { useEffect, useReducer, useRef } from "react";
import type {
  CoachDoc,
  Frame,
  HistoryPoint,
  MatchEvent,
  MatchStatus,
  Metadata,
  Meters,
  Overlay,
  Recap,
  TeamSummary,
  TraceStep,
} from "./types";

export interface MatchState {
  connected: boolean;
  running: boolean;
  status: MatchStatus;
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
  history: HistoryPoint[];
  coach: Record<string, CoachDoc>;
  archiveId: string | null;
  /** Set while the viewer is looking at an archived match; live messages are held back meanwhile. */
  viewing: { id: string; title: string; ended: string; startedAt: number } | null;
  /** The live room's status, kept fresh while viewing an archived match. */
  liveStatus: MatchStatus | null;
}

const initial: MatchState = {
  connected: false,
  running: false,
  status: { running: false, phase: "idle" },
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
  history: [],
  coach: {},
  archiveId: null,
  viewing: null,
  liveStatus: null,
};

type Action =
  | { type: "connected"; value: boolean }
  | { type: "message"; msg: { type: string; data: any } }
  | { type: "reset" }
  | { type: "archive"; doc: any }
  | { type: "live"; snapshot: any };

function fromSnapshot(state: MatchState, data: any): MatchState {
  const status: MatchStatus = data.status ?? { running: false };
  return {
    ...state,
    viewing: null,
    liveStatus: null,
    status,
    running: status.running ?? false,
    scenario: status.scenario ?? null,
    history: data.history ?? [],
    coach: data.coach ?? {},
    metadata: data.metadata,
    score: data.score ?? { home: 0, away: 0 },
    minute: data.minute ?? 0,
    meters: data.meters && Object.keys(data.meters).length ? data.meters : null,
    teams: data.teams ?? {},
    overlays: data.overlays ?? [],
    recap: data.recap ?? null,
    trace: data.trace ?? [],
    events: data.events ?? [],
    crewStats: data.crew_stats ?? {},
    languages: data.languages ?? ["en"],
    archiveId: data.archive_id ?? null,
    frame: null,
  };
}

function reducer(state: MatchState, action: Action): MatchState {
  if (action.type === "connected") return { ...state, connected: action.value };
  if (action.type === "reset")
    return { ...initial, connected: state.connected, running: true, status: { running: true, phase: "first_half" }, languages: state.languages };
  if (action.type === "live") return fromSnapshot(state, action.snapshot);
  if (action.type === "archive") {
    const d = action.doc;
    return {
      ...initial,
      connected: state.connected,
      status: { running: false, phase: "ended", ended: d.ended, seed: d.seed },
      metadata: d.metadata,
      minute: d.minute,
      score: d.score,
      overlays: d.overlays ?? [],
      recap: d.recap ?? null,
      coach: d.coach ?? {},
      history: d.history ?? [],
      events: d.events ?? [],
      trace: d.trace ?? [],
      crewStats: d.crew_stats ?? {},
      languages: d.languages ?? state.languages,
      scenario: d.scenario ? { title: d.scenario.title, storyline: d.scenario.storyline } : null,
      archiveId: d.id,
      liveStatus: state.viewing ? state.liveStatus : state.status,
      viewing: { id: d.id, title: d.title, ended: d.ended, startedAt: d.started_at },
    };
  }
  const { type, data } = action.msg;
  if (state.viewing && type !== "hello") {
    // Watching an archived match: keep the live room's status fresh but don't touch the view.
    return type === "status" ? { ...state, liveStatus: data } : state;
  }
  switch (type) {
    case "hello":
      return state.viewing ? state : fromSnapshot(state, data);
    case "metadata":
      return { ...state, metadata: data, running: true };
    case "frame":
      return { ...state, frame: data, minute: data.minute, score: data.score };
    case "meters":
      return {
        ...state,
        meters: data.meters,
        teams: data.teams,
        winProb: data.win_probability ?? state.winProb,
        history: data.point ? [...state.history, data.point] : state.history,
      };
    case "coach":
      return { ...state, coach: { ...state.coach, [data.side]: data } };
    case "overlay":
      return { ...state, overlays: [...state.overlays.slice(-160), data] };
    case "trace":
      return {
        ...state,
        trace: [...state.trace.slice(-300), data],
        crewStats: {
          ...state.crewStats,
          llm_calls: (state.crewStats.llm_calls ?? 0) + (data.agent === "match_director" && data.status === "skipped" ? 0 : 1),
          errors: (state.crewStats.errors ?? 0) + (data.status === "error" ? 1 : 0),
        },
      };
    case "event":
      return { ...state, events: [...state.events.slice(-80), data], score: data.score ?? state.score };
    case "recap":
      return { ...state, recap: data };
    case "status":
      return {
        ...state,
        status: data,
        running: data.running,
        scenario: data.scenario ?? state.scenario,
        archiveId: data.archive_id ?? state.archiveId,
      };
    default:
      return state;
  }
}

async function post(path: string, body?: unknown) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
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
    try {
      await post("/api/match/start", { seed, speed, source, brief });
    } catch (e) {
      dispatch({ type: "message", msg: { type: "status", data: { running: false, phase: "idle" } } });
      window.alert(
        `Couldn't reach the match room (${e instanceof Error ? e.message : e}). ` +
          "Check the server terminal is running and that the web app points at its port (GALLERY_API_PORT).",
      );
    }
  };

  const control = async (action: "pause" | "resume" | "end") => {
    try {
      await post(`/api/match/${action}`);
    } catch {
      /* the status message from the server is the source of truth */
    }
  };

  const openArchive = async (id: string) => {
    const r = await fetch(`/api/matches/${encodeURIComponent(id)}`);
    if (!r.ok) throw new Error("That match isn't in the archive any more.");
    dispatch({ type: "archive", doc: await r.json() });
  };

  const backToLive = async () => {
    const r = await fetch("/api/state");
    if (r.ok) dispatch({ type: "live", snapshot: await r.json() });
  };

  return { state, start, control, openArchive, backToLive };
}
