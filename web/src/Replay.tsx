import { useCallback, useEffect, useRef, useState } from "react";
import type { Frame, Metadata, Overlay, Prefs, ReplayFrame } from "./types";
import { Pitch } from "./Pitch";
import { NARRATIVE, pickVariant } from "./lib";
import { say, stopSpeaking } from "./audio";

/** How much of the match to show for a moment, and how fast (match-seconds per real second). */
export function clipFor(o: Overlay): {
  from: number;
  to: number;
  speed: number;
} {
  const s = o.show_at_second;
  if (o.kind === "tactical_shift") return { from: s - 30, to: s + 3, speed: 5 };
  if (o.kind === "match_status") return { from: s - 12, to: s, speed: 3 };
  return { from: s - 14, to: s + 4, speed: 2 };
}

/** Narrative moments the crew wrote (not plain data tags), which are the ones worth replaying. */
export const isReplayable = (o: Overlay) =>
  NARRATIVE.has(o.kind) &&
  !(o.produced_by.length === 1 && o.produced_by[0] === "stats_engine");

export interface Shot {
  t: number;
  t_end: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  outcome: string;
  player_id: string;
  side: "home" | "away" | null;
}

/** Visual effects for the current replay instant: the shot trail, the shooter's kick and the goal flash. */
export interface ReplayFx {
  trail?: [number, number, number, number];
  shooter?: string;
  kicking?: boolean;
  outcome?: string;
  goalSide?: "left" | "right" | null;
  slowmo?: boolean;
}

type Key = [number, number, number];

function ballAt(keys: Key[], t: number): [number, number] | null {
  if (!keys.length || t < keys[0][0] - 2) return null;
  let i = 0;
  while (i < keys.length - 1 && keys[i + 1][0] <= t) i++;
  const a = keys[i];
  const b = keys[Math.min(i + 1, keys.length - 1)];
  const k =
    b[0] === a[0] ? 0 : Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0])));
  return [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}

function lerpFrame(
  a: ReplayFrame,
  b: ReplayFrame,
  t: number,
  ball: [number, number] | null,
): Frame {
  const k =
    b[0] === a[0] ? 0 : Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0])));
  const nextPos = new Map(b[3].map(([id, x, y]) => [id, [x, y]] as const));
  return {
    second: t,
    minute: Math.floor(t / 60) + 1,
    ball: ball ?? [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k],
    players: a[3].map(([id, x, y]) => {
      const n = nextPos.get(id) ?? [x, y];
      return [id, x + (n[0] - x) * k, y + (n[1] - y) * k, 0];
    }),
    score: { home: 0, away: 0 },
  } as Frame;
}

function fxAt(
  shots: Shot[],
  t: number,
  ball: [number, number] | null,
): ReplayFx {
  const fx: ReplayFx = {};
  fx.slowmo = shots.some((s) => t > s.t - 2.2 && t < s.t_end + 1.5);
  const s = [...shots].reverse().find(
    (x) => t >= x.t - 0.5 && t <= x.t_end + (x.outcome === "goal" ? 3.5 : 1.4),
  );
  if (!s) return fx;
  const end: [number, number] = t >= s.t_end || !ball ? [s.x1, s.y1] : ball;
  if (t >= s.t) fx.trail = [s.x0, s.y0, end[0], end[1]];
  fx.shooter = s.player_id;
  fx.kicking = t >= s.t - 0.25 && t <= s.t + 0.35;
  fx.outcome = t >= s.t_end ? s.outcome : undefined;
  if (s.outcome === "goal" && t >= s.t_end)
    fx.goalSide = s.x1 > 52.5 ? "right" : "left";
  return fx;
}

/** Plays tracking frames for a time window, smoothly interpolated, on any <Pitch>. Shots play in slow motion. */
export function useReplay(archiveId: string | null, viewingArchive: boolean) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [fx, setFx] = useState<ReplayFx>({});
  const [active, setActive] = useState<Overlay | null>(null);
  const token = useRef(0);

  const stop = useCallback(() => {
    token.current += 1;
    setFrame(null);
    setFx({});
    setActive(null);
  }, []);

  const play = useCallback(
    async (
      o: Overlay,
      opts?: { from: number; to: number; speed: number },
    ): Promise<boolean> => {
      const mine = ++token.current;
      const c = opts ?? clipFor(o);
      setActive(o);
      const q = new URLSearchParams({
        from: String(Math.max(0, c.from)),
        to: String(c.to),
      });
      if (viewingArchive && archiveId) q.set("match", archiveId);
      let frames: ReplayFrame[] = [];
      let keys: Key[] = [];
      let shots: Shot[] = [];
      try {
        const r = await fetch(`/api/replay?${q}`);
        if (r.ok) {
          const d = await r.json();
          frames = d.frames ?? [];
          keys = d.ball ?? [];
          shots = d.shots ?? [];
        }
      } catch {
        /* no frames: the moment still shows its lower third */
      }
      if (mine !== token.current) return false;
      if (frames.length < 2) {
        await new Promise((res) => setTimeout(res, 2500));
        return mine === token.current;
      }
      const start = frames[0][0];
      // a goal clip runs on until the ball has sat in the net for a moment
      const goalEnd = Math.max(
        0,
        ...shots.filter((x) => x.outcome === "goal").map((x) => x.t_end + 3),
      );
      const end = Math.min(
        frames[frames.length - 1][0],
        Math.max(c.to, goalEnd),
      );
      await new Promise<void>((resolve) => {
        let i = 0;
        let t = start;
        let last = performance.now();
        const step = (now: number) => {
          if (mine !== token.current) return resolve();
          const dt = Math.min(0.1, (now - last) / 1000);
          last = now;
          const ballNow = ballAt(keys, t);
          const effects = fxAt(shots, t, ballNow);
          t += dt * (effects.slowmo ? Math.min(c.speed, 0.8) : c.speed);
          if (t >= end) return resolve();
          while (i < frames.length - 2 && frames[i + 1][0] <= t) i++;
          const f = lerpFrame(frames[i], frames[i + 1], t, ballNow);
          // tracking is 1 Hz, so pull the shooter onto the ball for the strike: the kick happens at his feet
          const shot = [...shots].reverse().find((x) => t > x.t - 2 && t < x.t_end + 3.5);
          if (shot) {
            const w = Math.min(1, Math.max(0, (t - (shot.t - 2)) / 1.6));
            const back = shot.x1 > shot.x0 ? -1.4 : 1.4;
            f.players = f.players.map((pl) =>
              pl[0] === shot.player_id
                ? [pl[0], pl[1] + (shot.x0 + back - pl[1]) * w, pl[2] + (shot.y0 - pl[2]) * w, 0]
                : pl,
            ) as Frame["players"];
          }
          setFrame(f);
          setFx(effects);
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
      return mine === token.current;
    },
    [archiveId, viewingArchive],
  );

  const activeRef = useRef<string | null>(null);
  activeRef.current = active?.overlay_id ?? null;
  const stopIf = useCallback(
    (id: string) => {
      if (activeRef.current === id) stop();
    },
    [stop],
  );

  useEffect(() => () => void (token.current += 1), []);
  return { frame, fx, active, play, stop, stopIf };
}

/** Auto-generated highlights: the goals and the biggest tactical shifts, replayed and narrated. */
export function pickHighlights(overlays: Overlay[], max = 7): Overlay[] {
  const moments = overlays.filter(isReplayable);
  const key = moments.filter((o) => o.kind === "key_moment");
  const shifts = moments
    .filter((o) => o.kind === "tactical_shift")
    .sort((a, b) => b.priority - a.priority)
    .slice(0, Math.max(2, max - key.length));
  return [...key, ...shifts]
    .sort((a, b) => a.show_at_second - b.show_at_second)
    .slice(0, max);
}

export function HighlightsReel({
  overlays,
  meta,
  prefs,
  archiveId,
  viewingArchive,
}: {
  overlays: Overlay[];
  meta: Metadata | null;
  prefs: Prefs;
  archiveId: string | null;
  viewingArchive: boolean;
}) {
  const reel = pickHighlights(overlays);
  const { frame, fx, active, play, stop } = useReplay(
    archiveId,
    viewingArchive,
  );
  const [index, setIndex] = useState(-1);
  const [narrate, setNarrate] = useState(true);
  const run = useRef(0);

  const playFrom = async (start: number) => {
    const mine = ++run.current;
    for (let i = start; i < reel.length; i++) {
      if (mine !== run.current) return;
      setIndex(i);
      const o = reel[i];
      const v = pickVariant(o, prefs);
      const voice = narrate
        ? say(`${v.headline}. ${v.body ?? ""}`, prefs.language)
        : Promise.resolve("none");
      const [finished] = await Promise.all([play(o), voice]);
      if (!finished || mine !== run.current) return;
      await new Promise((res) => setTimeout(res, 600));
    }
    if (mine === run.current) {
      setIndex(-1);
      stop();
    }
  };

  const halt = () => {
    run.current += 1;
    stopSpeaking();
    stop();
    setIndex(-1);
  };

  useEffect(
    () => () => {
      run.current += 1;
      stopSpeaking();
    },
    [],
  );

  if (!reel.length) return null;
  const playing = index >= 0;
  return (
    <section className="highlights" aria-label="Highlights">
      <header>
        <h3>Highlights · {reel.length} moments</h3>
        <label className="check">
          <input
            type="checkbox"
            checked={narrate}
            onChange={(e) => setNarrate(e.target.checked)}
          />
          <span>Narrate</span>
        </label>
        {playing ? (
          <>
            <button
              className="chip"
              disabled={index === 0}
              onClick={() => playFrom(index - 1)}
            >
              Previous
            </button>
            <button
              className="chip"
              disabled={index >= reel.length - 1}
              onClick={() => playFrom(index + 1)}
            >
              Next
            </button>
            <button className="primary" onClick={halt}>
              Stop
            </button>
          </>
        ) : (
          <button className="primary" onClick={() => playFrom(0)}>
            Watch highlights
          </button>
        )}
      </header>
      {playing && (
        <>
          <Pitch
            frame={frame}
            meta={meta}
            prefs={{ ...prefs, playerCam: "" }}
            lowerThird={active}
            shapeCallout={
              active?.evidence.some((e) => e.metric === "defensive_line_m")
                ? active
                : null
            }
            replayLabel={`${index + 1} of ${reel.length}`}
            fx={fx}
            emptyText="Loading the replay…"
          />
          <ol className="reel-steps" aria-label="Highlights in this reel">
            {reel.map((o, i) => (
              <li
                key={o.overlay_id}
                aria-current={i === index ? "step" : undefined}
              >
                <button onClick={() => playFrom(i)}>
                  {o.minute}' {pickVariant(o, prefs).headline}
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
