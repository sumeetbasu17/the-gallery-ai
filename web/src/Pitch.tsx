import type { CSSProperties } from "react";
import type { Frame, Metadata, Overlay, Prefs } from "./types";
import { pickVariant, playerName } from "./lib";

export interface PlayerStats {
  player?: string;
  distance_km?: number;
  top_speed_kmh?: number;
  passes?: number;
  pass_completion_pct?: number | null;
  shots?: number;
}

interface Props {
  frame: Frame | null;
  meta: Metadata | null;
  prefs: Prefs;
  lowerThird: Overlay | null;
  shapeCallout: Overlay | null;
  /** Shown as a broadcast "REPLAY" bug while a moment replay is playing. */
  replayLabel?: string | null;
  onExitReplay?: () => void;
  exitLabel?: string;
  camStats?: PlayerStats | null;
  onToggle3d?: () => void;
  emptyText?: string;
  /** Where the followed player has been: normalised counts on a rows x cols grid. */
  heat?: { cols: number; rows: number; grid: number[][] } | null;
  emptyCompact?: boolean;
}

const L = 105;
const W = 68;
// The SVG viewBox has a 2 m margin on every side; HTML billboards are positioned in the same space.
const left = (x: number) => `${((x + 2) / (L + 4)) * 100}%`;
const top = (y: number) => `${((y + 2) / (W + 4)) * 100}%`;

/**
 * The live pitch. Flat 2D by default; "3D" tilts it into a broadcast camera angle where players stand up
 * as tokens and the player cam follows its player with a floating stat card beside them.
 */
export function Pitch({
  frame,
  meta,
  prefs,
  lowerThird,
  shapeCallout,
  replayLabel,
  onExitReplay,
  exitLabel,
  camStats,
  onToggle3d,
  emptyText,
  heat,
  emptyCompact,
}: Props) {
  const homeIds = new Set(meta?.home.players.map((p) => p.id));
  const numbers = new Map<string, number>();
  meta?.home.players.forEach((p) => numbers.set(p.id, p.number));
  meta?.away.players.forEach((p) => numbers.set(p.id, p.number));
  const cam = prefs.playerCam;
  const is3d = prefs.view3d;

  const line = shapeCallout ? calloutGeometry(shapeCallout) : null;
  const third = lowerThird ? pickVariant(lowerThird, prefs) : null;
  const camPos = frame?.players.find(([id]) => id === cam);

  // Follow cam (3D only): centre the stage on the selected player.
  let stageStyle: CSSProperties | undefined;
  if (is3d && camPos) {
    const px = ((camPos[1] + 2) / (L + 4)) * 100;
    const py = ((camPos[2] + 2) / (W + 4)) * 100;
    stageStyle = {
      transform: `rotateX(52deg) scale(1.45) translate(${(50 - px).toFixed(2)}%, ${(50 - py).toFixed(2)}%)`,
    };
  }

  return (
    <div
      className={`pitch-wrap ${is3d ? "view3d" : ""} ${replayLabel ? "replaying" : ""}`}
    >
      <div className="pitch-stage" style={stageStyle}>
        <svg
          className="pitch"
          viewBox={`-2 -2 ${L + 4} ${W + 4}`}
          role="img"
          aria-label={replayLabel ? "Moment replay" : "Live pitch view"}
        >
          {Array.from({ length: 10 }).map((_, i) => (
            <rect
              key={i}
              x={i * 10.5}
              y={0}
              width={10.5}
              height={W}
              className={i % 2 ? "stripe-b" : "stripe-a"}
            />
          ))}
          <defs>
            <filter id="heatblur" x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation="1.8" />
            </filter>
          </defs>
          {heat && (
            <g className="heat" aria-label="Heatmap" filter="url(#heatblur)">
              {heat.grid.flatMap((row, r) =>
                row.map((v, c) =>
                  v > 0.04 ? (
                    <rect
                      key={`${r}-${c}`}
                      x={(c * L) / heat.cols}
                      y={(r * W) / heat.rows}
                      width={L / heat.cols}
                      height={W / heat.rows}
                      style={{ opacity: Math.min(0.85, 0.12 + v * 0.75) }}
                    />
                  ) : null,
                ),
              )}
            </g>
          )}
          <g className="markings">
            <rect x={0} y={0} width={L} height={W} />
            <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
            <circle cx={L / 2} cy={W / 2} r={9.15} />
            <rect x={0} y={13.84} width={16.5} height={40.32} />
            <rect x={L - 16.5} y={13.84} width={16.5} height={40.32} />
            <rect x={0} y={24.84} width={5.5} height={18.32} />
            <rect x={L - 5.5} y={24.84} width={5.5} height={18.32} />
            <rect
              x={-1.5}
              y={30.34}
              width={1.5}
              height={7.32}
              className="goal"
            />
            <rect x={L} y={30.34} width={1.5} height={7.32} className="goal" />
          </g>

          {line && (
            <g className="callout">
              {line.baseline !== null && (
                <>
                  <line
                    x1={line.baseline}
                    y1={1}
                    x2={line.baseline}
                    y2={W - 1}
                    className="callout-was"
                  />
                  <text
                    x={line.baseline}
                    y={W - 2.5}
                    className="callout-label muted"
                    textAnchor="middle"
                  >
                    was {line.baselineM} m
                  </text>
                </>
              )}
              <line
                x1={line.x}
                y1={1}
                x2={line.x}
                y2={W - 1}
                className="callout-now"
              />
              <text
                x={line.x}
                y={4.5}
                className="callout-label"
                textAnchor="middle"
              >
                now {line.valueM} m
              </text>
            </g>
          )}

          {!is3d &&
            frame?.players.map(([id, x, y]) => (
              <g
                key={id}
                transform={`translate(${x} ${y})`}
                className={cam === id ? "cam" : undefined}
              >
                {cam === id && <circle r={3.4} className="cam-ring" />}
                <circle
                  r={1.55}
                  className={homeIds.has(id) ? "dot-home" : "dot-away"}
                />
                <text y={0.62} textAnchor="middle" className="dot-num">
                  {numbers.get(id)}
                </text>
              </g>
            ))}
          {frame && !is3d && (
            <circle
              cx={frame.ball[0]}
              cy={frame.ball[1]}
              r={0.9}
              className="ball"
            />
          )}
        </svg>

        <div className="billboards" aria-hidden="true">
          {is3d &&
            frame?.players.map(([id, x, y]) => (
              <div
                key={id}
                className="token-anchor"
                style={{ left: left(x), top: top(y) }}
              >
                <span className={`token-foot ${cam === id ? "cam" : ""}`} />
                <span
                  className={`token ${homeIds.has(id) ? "home" : "away"} ${cam === id ? "cam" : ""}`}
                >
                  {numbers.get(id)}
                </span>
              </div>
            ))}
          {is3d && frame && (
            <div
              className="token-anchor"
              style={{ left: left(frame.ball[0]), top: top(frame.ball[1]) }}
            >
              <span className="token-foot small" />
              <span className="token ball3d" />
            </div>
          )}
          {camPos && (
            <div
              className="token-anchor card-anchor"
              style={{ left: left(camPos[1]), top: top(camPos[2]) }}
            >
              <div
                className={`cam-card ${!is3d && camPos[1] < 18 ? "edge-left" : !is3d && camPos[1] > 87 ? "edge-right" : ""}`}
              >
                <strong>{playerName(meta, cam)}</strong>
                {camStats && !("error" in camStats) && (
                  <span>
                    {camStats.distance_km} km · {camStats.top_speed_kmh} km/h ·{" "}
                    {camStats.passes} passes
                    {camStats.pass_completion_pct != null
                      ? ` (${camStats.pass_completion_pct}%)`
                      : ""}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {!frame && (
        <div className={`pitch-empty ${emptyCompact ? "compact" : ""}`}>
          <p>{emptyText ?? "The pitch comes alive at kick-off."}</p>
        </div>
      )}

      {onToggle3d && (
        <button
          className="view-toggle"
          onClick={onToggle3d}
          aria-pressed={is3d}
          title="Switch between the flat tactics board and a broadcast camera angle"
        >
          {is3d ? "◱ Back to 2D" : "◳ 3D camera"}
        </button>
      )}

      {replayLabel && (
        <div className="replay-bug" role="status">
          <span className="rec" aria-hidden="true" />
          Replay · {replayLabel}
          {onExitReplay && (
            <button onClick={onExitReplay} className="chip">
              {exitLabel ?? "Back to live"}
            </button>
          )}
        </div>
      )}

      {third && lowerThird && (
        <div
          key={lowerThird.overlay_id}
          className={`lower-third side-${lowerThird.side ?? "none"}`}
        >
          <span className="lt-minute">{lowerThird.minute}'</span>
          <div>
            <strong>{third.headline}</strong>
            {third.body && <p>{third.body}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function calloutGeometry(o: Overlay) {
  const ev = o.evidence.find((e) => e.metric === "defensive_line_m");
  if (!ev) return null;
  const toX = (m: number) => (o.side === "home" ? m : L - m);
  return {
    x: toX(ev.value),
    valueM: Math.round(ev.value),
    baseline: ev.baseline != null ? toX(ev.baseline) : null,
    baselineM: ev.baseline != null ? Math.round(ev.baseline) : null,
  };
}
