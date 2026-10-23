import type { Metadata, Overlay, Prefs, Variant } from "./types";

export const LANG_NAMES: Record<string, string> = { en: "English", hi: "हिन्दी", es: "Español" };

export const AGENT_NAMES: Record<string, string> = {
  stats_engine: "Stats engine",
  match_director: "Match Director",
  tactical_analyst: "Tactical Analyst",
  moment_judge: "Moment Judge",
  storyteller: "Storyteller",
  fact_checker: "Fact-Checker",
  fan_producer: "Fan Producer",
  recap_writer: "Recap writer",
};

export const METRIC_LABELS: Record<string, string> = {
  defensive_line_m: "Defensive line from own goal (m)",
  team_width_m: "Team width (m)",
  ppda: "PPDA (lower = more pressing)",
  field_tilt_pct: "Share of final-third passes (%)",
  pass_difficulty: "Pass difficulty (0-100)",
  pass_distance_m: "Pass distance (m)",
  lines_broken: "Defenders bypassed",
  ball_speed_kmh: "Ball speed (km/h)",
  shot_speed_kmh: "Shot speed (km/h)",
  speed_kmh: "Speed (km/h)",
  distance_covered_km: "Distance covered (km)",
  xg: "Expected goals (xG)",
  distance_m: "Distance to goal (m)",
  score_home: "Home goals",
  score_away: "Away goals",
  consecutive_completed_passes: "Passes in a row",
};

export const NARRATIVE = new Set(["tactical_shift", "key_moment", "match_status"]);

export function pickVariant(o: Overlay, prefs: Prefs): Variant {
  const lang = o.variants[prefs.language] ?? o.variants.en ?? Object.values(o.variants)[0];
  if (!lang) return { headline: o.headline, body: o.body ?? "" };
  const base = lang[prefs.audience] ?? lang.casual ?? { headline: o.headline, body: o.body ?? "" };
  if (prefs.lens !== "neutral" && NARRATIVE.has(o.kind)) {
    const club = lang[prefs.lens === "home" ? "home_fans" : "away_fans"];
    if (club?.body) return { headline: base.headline, body: club.body };
  }
  return base;
}

export function playerName(meta: Metadata | null, id?: string | null): string {
  if (!meta || !id) return "";
  for (const t of [meta.home, meta.away]) {
    const p = t.players.find((x) => x.id === id);
    if (p) return p.name;
  }
  return "";
}

export function teamOf(meta: Metadata | null, side?: string | null) {
  if (!meta || !side) return null;
  return side === "home" ? meta.home : meta.away;
}

export function fmt(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number.isInteger(v) ? String(v) : v.toFixed(digits);
}

export function speak(text: string, lang: string) {
  if (!("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === "hi" ? "hi-IN" : lang === "es" ? "es-ES" : "en-GB";
  u.rate = 1.02;
  window.speechSynthesis.speak(u);
  return true;
}
