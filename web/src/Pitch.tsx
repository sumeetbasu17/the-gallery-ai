import type { Frame, Metadata, Overlay, Prefs } from "./types";
import { pickVariant, playerName } from "./lib";

interface Props {
  frame: Frame | null;
  meta: Metadata | null;
  prefs: Prefs;
  lowerThird: Overlay | null;
  shapeCallout: Overlay | null;
}

const L = 105;
const W = 68;

/** Live 2D pitch. The tactical callout draws the analyst's evidence onto the grass itself. */
export function Pitch({ frame, meta, prefs, lowerThird, shapeCallout }: Props) {
  const homeIds = new Set(meta?.home.players.map((p) => p.id));
  const numbers = new Map<string, number>();
  meta?.home.players.forEach((p) => numbers.set(p.id, p.number));
  meta?.away.players.forEach((p) => numbers.set(p.id, p.number));
  const cam = prefs.playerCam;

  const line = shapeCallout ? calloutGeometry(shapeCallout) : null;
  const third = lowerThird ? pickVariant(lowerThird, prefs) : null;

  return (
    <div className="pitch-wrap">
      <svg className="pitch" viewBox={`-2 -2 ${L + 4} ${W + 4}`} role="img" aria-label="Live pitch view">
        {Array.from({ length: 10 }).map((_, i) => (
          <rect key={i} x={i * 10.5} y={0} width={10.5} height={W} className={i % 2 ? "stripe-b" : "stripe-a"} />
        ))}
        <g className="markings">
          <rect x={0} y={0} width={L} height={W} />
          <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
          <circle cx={L / 2} cy={W / 2} r={9.15} />
          <rect x={0} y={13.84} width={16.5} height={40.32} />
          <rect x={L - 16.5} y={13.84} width={16.5} height={40.32} />
          <rect x={0} y={24.84} width={5.5} height={18.32} />
          <rect x={L - 5.5} y={24.84} width={5.5} height={18.32} />
          <rect x={-1.5} y={30.34} width={1.5} height={7.32} className="goal" />
          <rect x={L} y={30.34} width={1.5} height={7.32} className="goal" />
        </g>

        {line && (
          <g className="callout">
            {line.baseline !== null && (
              <>
                <line x1={line.baseline} y1={1} x2={line.baseline} y2={W - 1} className="callout-was" />
                <text x={line.baseline} y={W - 2.5} className="callout-label muted" textAnchor="middle">
                  was {line.baselineM} m
                </text>
              </>
            )}
            <line x1={line.x} y1={1} x2={line.x} y2={W - 1} className="callout-now" />
            <text x={line.x} y={4.5} className="callout-label" textAnchor="middle">
              now {line.valueM} m
            </text>
          </g>
        )}

        {frame?.players.map(([id, x, y]) => {
          const home = homeIds.has(id);
          const isCam = cam === id;
          return (
            <g key={id} transform={`translate(${x} ${y})`} className={isCam ? "cam" : undefined}>
              {isCam && <circle r={3.4} className="cam-ring" />}
              <circle r={1.55} className={home ? "dot-home" : "dot-away"} />
              <text y={0.62} textAnchor="middle" className="dot-num">
                {numbers.get(id)}
              </text>
              {isCam && (
                <text y={-4.2} textAnchor="middle" className="cam-name">
                  {playerName(meta, id)}
                </text>
              )}
            </g>
          );
        })}
        {frame && <circle cx={frame.ball[0]} cy={frame.ball[1]} r={0.9} className="ball" />}
      </svg>

      {!frame && (
        <div className="pitch-empty">
          <p>The pitch comes alive at kick-off.</p>
        </div>
      )}

      {third && lowerThird && (
        <div key={lowerThird.overlay_id} className={`lower-third side-${lowerThird.side ?? "none"}`}>
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
