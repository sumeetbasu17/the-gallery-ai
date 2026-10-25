import type { Focus, Metadata, Meters as M, TeamSummary } from "./types";
import { fmt } from "./lib";

interface Props {
  meters: M | null;
  meta: Metadata | null;
  teams: Record<string, TeamSummary>;
  winProb: Record<string, number> | null;
  focus: Focus;
  analyst: boolean;
}

export function Meters({
  meters,
  meta,
  teams,
  winProb,
  focus,
  analyst,
}: Props) {
  if (!meters || !meta)
    return (
      <div className="meters placeholder">
        Meters start after a few minutes of play.
      </div>
    );
  const h = meta.home.name;
  const a = meta.away.name;
  const cvc = meters.control_vs_chaos;
  const show = (f: Focus) => focus === "all" || focus === f;

  return (
    <section
      className={`meters ${focus !== "all" ? "focused" : ""}`}
      aria-label="Match meters"
    >
      {show("control") && (
        <div className="meter">
          <h4>Control vs chaos</h4>
          <Scale value={cvc.control} left="Chaos" right="Control" />
          <p className="meter-read">
            {cvc.label === "controlled" && cvc.in_control
              ? `${cvc.in_control} are running the game`
              : capital(cvc.label)}
            {` (both teams, last ${meters.window_minutes} min)`}
          </p>
          {analyst && (
            <dl className="meter-detail">
              <dt>Turnovers / min</dt>
              <dd>{fmt(cvc.turnovers_per_min, 2)}</dd>
              <dt>Passes under pressure</dt>
              <dd>{fmt(cvc.passes_under_pressure_pct)}%</dd>
              <dt>Passes per possession</dt>
              <dd>{fmt(cvc.avg_passes_per_possession)}</dd>
              <dt>Field tilt</dt>
              <dd>
                {fmt(cvc.field_tilt_pct[h])}% – {fmt(cvc.field_tilt_pct[a])}%
              </dd>
              <dt>Possession (5 min)</dt>
              <dd>
                {fmt(cvc.possession_pct[h])}% – {fmt(cvc.possession_pct[a])}%
              </dd>
            </dl>
          )}
        </div>
      )}
      {show("pressure") && (
        <div className="meter">
          <h4>Pressure</h4>
          <Split
            left={meta.home.short_name}
            right={meta.away.short_name}
            l={meters.pressure[h]?.pressing_actions_per_min ?? 0}
            r={meters.pressure[a]?.pressing_actions_per_min ?? 0}
          />
          <p className="meter-read">
            Pressing actions per minute, last {meters.window_minutes} min
          </p>
          {analyst && (
            <dl className="meter-detail">
              <dt>PPDA {meta.home.short_name}</dt>
              <dd>{fmt(meters.pressure[h]?.ppda_10min)}</dd>
              <dt>PPDA {meta.away.short_name}</dt>
              <dd>{fmt(meters.pressure[a]?.ppda_10min)}</dd>
            </dl>
          )}
        </div>
      )}
      {show("rhythm") && (
        <div className="meter">
          <h4>Rhythm</h4>
          <Scale
            value={Math.min(100, (meters.rhythm.passes_per_min / 18) * 100)}
            left="Slow"
            right="Frantic"
          />
          <p className="meter-read">
            {capital(meters.rhythm.label)}: {fmt(meters.rhythm.passes_per_min)}{" "}
            passes a minute, both teams
          </p>
          {analyst && (
            <dl className="meter-detail">
              <dt>Completion {meta.home.short_name}</dt>
              <dd>{meters.rhythm.completion_pct[h]}%</dd>
              <dt>Completion {meta.away.short_name}</dt>
              <dd>{meters.rhythm.completion_pct[a]}%</dd>
            </dl>
          )}
        </div>
      )}
      {focus === "all" && analyst && teams[h] && teams[a] && (
        <div className="meter">
          <h4>Totals</h4>
          <dl className="meter-detail totals">
            <dt>xG</dt>
            <dd>
              {fmt(teams[h].xg, 2)} – {fmt(teams[a].xg, 2)}
            </dd>
            <dt>Shots</dt>
            <dd>
              {teams[h].shots} – {teams[a].shots}
            </dd>
            <dt>Possession</dt>
            <dd>
              {teams[h].possession_pct}% – {teams[a].possession_pct}%
            </dd>
            <dt>Shape</dt>
            <dd>
              {teams[h].block ?? "–"} / {teams[a].block ?? "–"}
            </dd>
          </dl>
        </div>
      )}
      {winProb && focus === "all" && (
        <div className="meter">
          <h4>Win probability</h4>
          <div className="wp-bar" role="img" aria-label="Win probability">
            <span className="wp-home" style={{ flexBasis: `${winProb[h]}%` }}>
              {winProb[h]}%
            </span>
            <span className="wp-draw" style={{ flexBasis: `${winProb.draw}%` }}>
              {winProb.draw}%
            </span>
            <span className="wp-away" style={{ flexBasis: `${winProb[a]}%` }}>
              {winProb[a]}%
            </span>
          </div>
          <p className="meter-read">
            {meta.home.short_name} · draw · {meta.away.short_name}
          </p>
        </div>
      )}
    </section>
  );
}

function Scale({
  value,
  left,
  right,
}: {
  value: number;
  left: string;
  right: string;
}) {
  return (
    <div
      className="scale"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
    >
      <div className="scale-track">
        <div
          className="scale-mark"
          style={{ left: `${Math.max(2, Math.min(98, value))}%` }}
        />
      </div>
      <div className="scale-ends">
        <span>{left}</span>
        <span>{right}</span>
      </div>
    </div>
  );
}

function Split({
  left,
  right,
  l,
  r,
}: {
  left: string;
  right: string;
  l: number;
  r: number;
}) {
  const total = l + r || 1;
  return (
    <div className="split">
      <div className="split-bar">
        <span
          className="wp-home"
          style={{ flexBasis: `${(l / total) * 100}%` }}
        />
        <span
          className="wp-away"
          style={{ flexBasis: `${(r / total) * 100}%` }}
        />
      </div>
      <div className="scale-ends">
        <span>
          {left} {fmt(l)}
        </span>
        <span>
          {fmt(r)} {right}
        </span>
      </div>
    </div>
  );
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
