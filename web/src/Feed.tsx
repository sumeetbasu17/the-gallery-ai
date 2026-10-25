import { useState } from "react";
import type { Metadata, Overlay, Prefs } from "./types";
import {
  AGENT_NAMES,
  METRIC_LABELS,
  NARRATIVE,
  fmt,
  pickVariant,
  playerName,
  teamOf,
} from "./lib";
import { isReplayable } from "./Replay";

interface Props {
  overlays: Overlay[];
  meta: Metadata | null;
  prefs: Prefs;
  onTerm: (term: string) => void;
  onReplay?: (o: Overlay) => void;
  replaying?: string | null;
  onClearPlayer?: () => void;
}

/** Does this moment involve the player: tagged with them, or the crew's story names them? */
function involves(o: Overlay, id: string, name: string): boolean {
  if (o.player_id === id) return true;
  if (!name || !NARRATIVE.has(o.kind)) return false;
  const surname = name.split(" ").slice(-1)[0];
  const texts = [
    o.headline,
    o.body ?? "",
    ...Object.values(o.variants).flatMap((v) =>
      Object.values(v).flatMap((x) => [x.headline, x.body]),
    ),
  ];
  return texts.some(
    (t) =>
      t && (t.includes(name) || (surname.length > 3 && t.includes(surname))),
  );
}

const TAG_KINDS = new Set([
  "player_tag",
  "pass_quality",
  "shot_speed",
  "milestone",
]);

export function Feed({
  overlays,
  meta,
  prefs,
  onTerm,
  onReplay,
  replaying,
  onClearPlayer,
}: Props) {
  const camName = playerName(meta, prefs.playerCam);
  const visible = overlays
    .filter((o) => {
      if (prefs.playerCam) return involves(o, prefs.playerCam, camName);
      if (NARRATIVE.has(o.kind)) return true;
      if (prefs.audience === "casual")
        return o.kind === "milestone" && o.priority >= 45;
      return TAG_KINDS.has(o.kind);
    })
    // newest moment first by match time: a story the crew finishes late still lands in the right place
    .map((o, i) => [o, i] as const)
    .sort((a, b) => b[0].show_at_second - a[0].show_at_second || b[1] - a[1])
    .map(([o]) => o);

  const hint = prefs.playerCam
    ? `${camName}'s match: ${visible.length} moment${visible.length === 1 ? "" : "s"} involving them (goals, cards, data tags and every insight that names them).`
    : prefs.audience === "casual"
      ? "Casual: the big moments only. The Match Director airs at most three every five minutes, like a real broadcast. Switch to Analyst for every data tag."
      : "Analyst: every insight plus live data tags (pass difficulty, sprints, shot speed, passing streaks).";

  if (!visible.length) {
    return (
      <div className="feed-empty">
        <p>
          Insights land here as the crew spots them. Tactical changes usually
          start showing after the first 15 minutes.
        </p>
        <p className="feed-hint">
          {prefs.playerCam
            ? `Nothing involving ${camName} yet. Their live stats and heatmap are above.`
            : hint}
          {prefs.playerCam && onClearPlayer && (
            <button className="term" onClick={onClearPlayer}>
              Show all moments
            </button>
          )}
        </p>
      </div>
    );
  }
  return (
    <>
      <p className="feed-hint">
        {hint}{" "}
        {prefs.playerCam && onClearPlayer && (
          <button className="term" onClick={onClearPlayer}>
            Show all moments
          </button>
        )}
      </p>
      <ol className="feed" aria-live="polite">
        {visible.map((o) =>
          NARRATIVE.has(o.kind) ? (
            <Insight
              key={o.overlay_id}
              o={o}
              meta={meta}
              prefs={prefs}
              onTerm={onTerm}
              onReplay={onReplay}
              replaying={replaying === o.overlay_id}
            />
          ) : (
            <Tag key={o.overlay_id} o={o} prefs={prefs} />
          ),
        )}
      </ol>
    </>
  );
}

function Tag({ o, prefs }: { o: Overlay; prefs: Prefs }) {
  const v = pickVariant(o, prefs);
  return (
    <li className={`tag side-${o.side ?? "none"}`}>
      <span className="minute">{o.minute}'</span>
      <span className="tag-text">
        <strong>{v.headline}</strong>
        {v.body && v.body !== v.headline && (
          <span className="tag-sub">
            {prefs.audience === "analyst" ? o.body : v.body}
          </span>
        )}
      </span>
    </li>
  );
}

function Insight({
  o,
  meta,
  prefs,
  onTerm,
  onReplay,
  replaying,
}: {
  o: Overlay;
  meta: Metadata | null;
  prefs: Prefs;
  onTerm: (t: string) => void;
  onReplay?: (o: Overlay) => void;
  replaying?: boolean;
}) {
  const [open, setOpen] = useState(
    prefs.audience === "analyst" && o.kind === "tactical_shift",
  );
  const v = pickVariant(o, prefs);
  const team = teamOf(meta, o.side);
  return (
    <li
      className={`insight side-${o.side ?? "none"} kind-${o.kind} ${replaying ? "replaying" : ""}`}
    >
      <span className="minute big">{o.minute}'</span>
      <div className="insight-main">
        <h3>{v.headline}</h3>
        {v.body && <p>{v.body}</p>}
        <div className="insight-meta">
          {team && <span className="team-chip">{team.short_name}</span>}
          <Badge o={o} />
          {onReplay && isReplayable(o) && (
            <button
              className="show-me"
              onClick={() => onReplay(o)}
              aria-pressed={replaying}
            >
              {replaying ? "Replaying…" : "▶ Show me"}
            </button>
          )}
          {prefs.audience === "casual" &&
            o.glossary_terms.map((t) => (
              <button key={t} className="term" onClick={() => onTerm(t)}>
                What's "{t}"?
              </button>
            ))}
          <button
            className="why"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide why" : "Why?"}
          </button>
        </div>
        {open && <Why o={o} meta={meta} onTerm={onTerm} />}
      </div>
    </li>
  );
}

function Why({
  o,
  meta,
  onTerm,
}: {
  o: Overlay;
  meta: Metadata | null;
  onTerm: (t: string) => void;
}) {
  const wp = o.win_probability;
  return (
    <div className="why-panel">
      {o.importance_reason && <p className="stakes">{o.importance_reason}</p>}
      {o.evidence.length > 0 && (
        <table className="evidence">
          <thead>
            <tr>
              <th scope="col">Evidence</th>
              <th scope="col">Now</th>
              <th scope="col">Before</th>
            </tr>
          </thead>
          <tbody>
            {o.evidence.map((e, i) => (
              <tr key={i}>
                <td>
                  {METRIC_LABELS[e.metric] ?? e.metric}
                  {e.window && <span className="window"> ({e.window})</span>}
                </td>
                <td className="num">{fmt(e.value)}</td>
                <td className="num">
                  {e.baseline != null ? fmt(e.baseline) : "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {wp && meta && (
        <p className="wp-line">
          Win probability: {meta.home.short_name} {wp[meta.home.name]}% · draw{" "}
          {wp.draw}% · {meta.away.short_name} {wp[meta.away.name]}%
        </p>
      )}
      {o.player_id && (
        <p className="wp-line">Player: {playerName(meta, o.player_id)}</p>
      )}
      <ol className="chain" aria-label="How the crew produced this">
        {dedupe(o.trace).map((s, i) => (
          <li
            key={i}
            className={`step status-${s.status}`}
            title={s.note ?? s.action}
          >
            <span className="step-agent">
              {AGENT_NAMES[s.agent] ?? s.agent}
            </span>
            <span className="step-action">{s.action}</span>
            {s.status !== "ok" && (
              <span className="step-status">{s.status}</span>
            )}
            {s.note && s.status !== "ok" && (
              <span className="step-note">{s.note}</span>
            )}
          </li>
        ))}
      </ol>
      {o.glossary_terms.length > 0 && (
        <p className="terms">
          Terms:{" "}
          {o.glossary_terms.map((t) => (
            <button key={t} className="term" onClick={() => onTerm(t)}>
              {t}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}

function dedupe(trace: Overlay["trace"]) {
  // Collapse repeated per-language Fan Producer hops into one line for readability.
  const out: Overlay["trace"] = [];
  for (const s of trace) {
    const prev = out[out.length - 1];
    if (
      prev &&
      prev.agent === s.agent &&
      prev.status === s.status &&
      s.agent === "fan_producer"
    ) {
      prev.action = "personalise for every language";
      continue;
    }
    out.push({ ...s });
  }
  return out;
}

function Badge({ o }: { o: Overlay }) {
  if (o.produced_by.length === 1 && o.produced_by[0] === "stats_engine")
    return (
      <span
        className="data-chip"
        title="Straight from the stats engine: no AI wording, nothing to fact-check"
      >
        Live data
      </span>
    );
  const level = o.check_level ?? (o.verified ? "full" : "template");
  if (level === "full")
    return (
      <span
        className="checked"
        title="Numbers, names and wording were checked against the stats engine"
      >
        Fact-checked
      </span>
    );
  if (level === "numbers")
    return (
      <span
        className="numbers-checked"
        title="Every number, name and direction was verified; the wording review flagged a detail"
      >
        Numbers checked
      </span>
    );
  return (
    <span
      className="unchecked"
      title="The story didn't pass checks, so a plain factual template aired"
    >
      Template
    </span>
  );
}
