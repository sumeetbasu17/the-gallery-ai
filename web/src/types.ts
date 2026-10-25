export type Side = "home" | "away";
export type Audience = "casual" | "analyst";
export type Lens = "neutral" | "home" | "away";
export type Focus = "all" | "control" | "pressure" | "rhythm";

export interface Player {
  id: string;
  name: string;
  number: number;
  position: string;
  side: Side;
}

export interface Team {
  id: string;
  name: string;
  short_name: string;
  side: Side;
  formation: string;
  players: Player[];
}

export interface Metadata {
  match_id: string;
  venue: string;
  home: Team;
  away: Team;
}

export interface Evidence {
  metric: string;
  value: number;
  baseline?: number | null;
  window?: string | null;
  source_tool?: string | null;
}

export interface Variant {
  headline: string;
  body: string;
}

export interface AgentStep {
  agent: string;
  action: string;
  status: "ok" | "retry" | "rejected" | "fallback" | "skipped" | "error";
  ms: number;
  note?: string | null;
}

export interface Overlay {
  overlay_id: string;
  kind:
    | "player_tag"
    | "pass_quality"
    | "shot_speed"
    | "tactical_shift"
    | "key_moment"
    | "milestone"
    | "meter_update"
    | "match_status"
    | "recap";
  show_at_second: number;
  duration_s: number;
  priority: number;
  headline: string;
  body?: string | null;
  player_id?: string | null;
  side?: Side | null;
  evidence: Evidence[];
  verified: boolean;
  check_level?: "full" | "numbers" | "template";
  produced_by: string[];
  glossary_terms: string[];
  minute: number;
  importance_reason?: string | null;
  variants: Record<string, Record<string, Variant>>;
  trace: AgentStep[];
  win_probability?: Record<string, number> | null;
}

export interface Frame {
  second: number;
  minute: number;
  ball: [number, number];
  players: [string, number, number, number][];
  score: { home: number; away: number };
}

export interface Meters {
  window_minutes: number;
  control_vs_chaos: {
    control: number;
    label: string;
    in_control: string | null;
    turnovers_per_min: number;
    passes_under_pressure_pct: number;
    long_ball_pct: number;
    avg_passes_per_possession: number;
    possession_pct: Record<string, number>;
    field_tilt_pct: Record<string, number>;
  };
  pressure: Record<string, { pressing_actions_per_min: number; ppda_10min: number | null }>;
  rhythm: { passes_per_min: number; label: string; completion_pct: Record<string, number> };
}

export interface TeamSummary {
  goals: number;
  shots: number;
  on_target: number;
  xg: number;
  passes: number;
  pass_completion_pct: number | null;
  possession_pct: number;
  block: string | null;
  width: string | null;
}

export interface TraceStep {
  agent: string;
  action: string;
  status: string;
  ms: number;
  minute: number;
  note?: string;
}

export interface Recap {
  translations?: Record<string, { headline: string; paragraphs: string[] }>;
  stopped_at?: number | null;
  recap: {
    headline: string;
    paragraphs: string[];
    key_moments: string[];
    player_of_the_match: string;
    player_of_the_match_reason: string;
  };
  facts: Record<string, unknown>;
}

export interface MatchEvent {
  type: string;
  minute: number;
  side?: Side;
  player?: string;
  score: { home: number; away: number };
}

export interface Prefs {
  audience: Audience;
  lens: Lens;
  language: string;
  playerCam: string;
  focus: Focus;
  voice: boolean;
  view3d: boolean;
}

export interface MatchStatus {
  running: boolean;
  paused?: boolean;
  phase?: "idle" | "first_half" | "half_time" | "second_half" | "finishing" | "ended";
  can_pause?: boolean;
  ended?: "full_time" | "stopped";
  seed?: number | null;
  speed?: number | null;
  source?: string;
  archive_id?: string;
  scenario?: { title?: string; storyline?: string } | null;
}

/** A compact replay frame: [second, ballX, ballY, [[playerId, x, y], ...]] */
export type ReplayFrame = [number, number, number, [string, number, number][]];

export interface ArchiveSummary {
  id: string;
  title: string;
  home: string;
  away: string;
  score: { home: number; away: number };
  minute: number;
  ended: "full_time" | "stopped";
  seed: number;
  speed: number;
  scenario_title?: string | null;
  started_at: number;
  ended_at: number;
  headline?: string | null;
  insights: number;
  source?: string;
}

export interface HistoryPoint {
  minute: number;
  second: number;
  home: number;
  draw: number;
  away: number;
  tilt_home: number;
  control: number;
}

export interface CoachDoc {
  side: Side;
  club: string;
  minute: number;
  kind?: "half_time" | "on_demand";
  verified: boolean;
  report: {
    headline: string;
    working: string[];
    not_working: string[];
    changes: { change: string; why: string }[];
  } | null;
}

export interface PunditReply {
  question: string;
  answer: string;
  verified: boolean;
  on_topic?: boolean;
  terms: string[];
  minute?: number;
}
