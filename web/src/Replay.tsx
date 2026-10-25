import { useCallback, useEffect, useRef, useState } from "react";
import type { Frame, Metadata, Overlay, Prefs, ReplayFrame } from "./types";
import { Pitch } from "./Pitch";
import { NARRATIVE, pickVariant } from "./lib";
import { say, stopSpeaking } from "./audio";

/** How much of the match to show for a moment, and how fast (match-seconds per real second). */
export function clipFor(o: Overlay): { from: number; to: number; speed: number } {
  const s = o.show_at_second;
  if (o.kind === "tactical_shift") return { from: s - 30, to: s + 3, speed: 5 };
  if (o.kind === "match_status") return { from: s - 12, to: s, speed: 3 };
  return { from: s - 14, to: s + 4, speed: 2 };
}

/** Narrative moments the crew wrote (not plain data tags), which are the ones worth replaying. */
export const isReplayable = (o: Overlay) =>
  NARRATIVE.has(o.kind) && !(o.produced_by.length === 1 && o.produced_by[0] === "stats_engine");

function lerpFrame(a: ReplayFrame, b: ReplayFrame, t: number): Frame {
  const k = b[0] === a[0] ? 0 : Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0])));
  const nextPos = new Map(b[3].map(([id, x, y]) => [id, [x, y]] as const));
  return {
    second: t,
    minute: Math.floor(t / 60) + 1,
    ball: [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k],
    players: a[3].map(([id, x, y]) => {
      const n = nextPos.get(id) ?? [x, y];
      return [id, x + (n[0] - x) * k, y + (n[1] - y) * k, 0];
    }),
    score: { home: 0, away: 0 },
  } as Frame;
}

/** Plays tracking frames for a time window, smoothly interpolated, on any <Pitch>. */
export function useReplay(archiveId: string | null, viewingArchive: boolean) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [active, setActive] = useState<Overlay | null>(null);
  const token = useRef(0);

  const stop = useCallback(() => {
    token.current += 1;
    setFrame(null);
    setActive(null);
  }, []);

  const play = useCallback(
    async (o: Overlay, opts?: { from: number; to: number; speed: number }): Promise<boolean> => {
      const mine = ++token.current;
      const c = opts ?? clipFor(o);
      setActive(o);
      const q = new URLSearchParams({ from: String(Math.max(0, c.from)), to: String(c.to) });
      if (viewingArchive && archiveId) q.set("match", archiveId);
      let frames: ReplayFrame[] = [];
      try {
        const r = await fetch(`/api/replay?${q}`);
        if (r.ok) frames = (await r.json()).frames ?? [];
      } catch {
        /* no frames: the moment still shows its lower third */
      }
      if (mine !== token.current) return false;
      if (frames.length < 2) {
        await new Promise((res) => setTimeout(res, 2500));
        return mine === token.current;
      }
      const t0 = performance.now();
      const start = frames[0][0];
      const end = frames[frames.length - 1][0];
      await new Promise<void>((resolve) => {
        let i = 0;
        const step = (now: number) => {
          if (mine !== token.current) return resolve();
          const t = start + ((now - t0) / 1000) * c.speed;
          if (t >= end) {
            setFrame(lerpFrame(frames[frames.length - 1], frames[frames.length - 1], end));
            return resolve();
          }
          while (i < frames.length - 2 && frames[i + 1][0] <= t) i++;
          setFrame(lerpFrame(frames[i], frames[i + 1], t));
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
  const stopIf = useCallback((id: string) => {
    if (activeRef.current === id) stop();
  }, [stop]);

  useEffect(() => () => void (token.current += 1), []);
  return { frame, active, play, stop, stopIf };
}

/** Auto-generated highlights: the goals and the biggest tactical shifts, replayed and narrated. */
export function pickHighlights(overlays: Overlay[], max = 7): Overlay[] {
  const moments = overlays.filter(isReplayable);
  const key = moments.filter((o) => o.kind === "key_moment");
  const shifts = moments
    .filter((o) => o.kind === "tactical_shift")
    .sort((a, b) => b.priority - a.priority)
    .slice(0, Math.max(2, max - key.length));
  return [...key, ...shifts].sort((a, b) => a.show_at_second - b.show_at_second).slice(0, max);
}

export function HighlightsReel({ overlays, meta, prefs, archiveId, viewingArchive }: {
  overlays: Overlay[];
  meta: Metadata | null;
  prefs: Prefs;
  archiveId: string | null;
  viewingArchive: boolean;
}) {
  const reel = pickHighlights(overlays);
  const { frame, active, play, stop } = useReplay(archiveId, viewingArchive);
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
      const voice = narrate ? say(`${v.headline}. ${v.body ?? ""}`, prefs.language) : Promise.resolve("none");
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

  useEffect(() => () => {
    run.current += 1;
    stopSpeaking();
  }, []);

  if (!reel.length) return null;
  const playing = index >= 0;
  return (
    <section className="highlights" aria-label="Highlights">
      <header>
        <h3>Highlights · {reel.length} moments</h3>
        <label className="check">
          <input type="checkbox" checked={narrate} onChange={(e) => setNarrate(e.target.checked)} />
          <span>Narrate</span>
        </label>
        {playing ? (
          <>
            <button className="chip" disabled={index === 0} onClick={() => playFrom(index - 1)}>
              Previous
            </button>
            <button className="chip" disabled={index >= reel.length - 1} onClick={() => playFrom(index + 1)}>
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
            shapeCallout={active?.evidence.some((e) => e.metric === "defensive_line_m") ? active : null}
            replayLabel={`${index + 1} of ${reel.length}`}
            emptyText="Loading the replay…"
          />
          <ol className="reel-steps" aria-label="Highlights in this reel">
            {reel.map((o, i) => (
              <li key={o.overlay_id} aria-current={i === index ? "step" : undefined}>
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
