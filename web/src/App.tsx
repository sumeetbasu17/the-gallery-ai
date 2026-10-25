import { useCallback, useEffect, useRef, useState } from "react";
import { Feed } from "./Feed";
import { Meters } from "./Meters";
import {
  ArchiveList,
  Controls,
  GlossaryDialog,
  Kickoff,
  PlayerCard,
  Producer,
  RecapView,
} from "./Panels";
import {
  AskPundit,
  CoachView,
  PlayerReportBox,
  StoryChart,
  TeamStats,
} from "./Extras";
import { Pitch, type PlayerStats } from "./Pitch";
import { HighlightsReel, useReplay } from "./Replay";
import { NARRATIVE, pickVariant, playerName } from "./lib";
import { say, stopSpeaking } from "./audio";
import type { Overlay, Prefs } from "./types";
import { useMatch } from "./useMatch";

const DEFAULT_PREFS: Prefs = {
  audience: "casual",
  lens: "neutral",
  language: "en",
  playerCam: "",
  focus: "all",
  voice: false,
  view3d: false,
};
const LOWER_THIRD_MS = 9000;

function loadPrefs(): Prefs {
  try {
    return {
      ...DEFAULT_PREFS,
      ...JSON.parse(localStorage.getItem("gallery-prefs") ?? "{}"),
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

type Tab = "live" | "coach" | "producer" | "recap" | "matches";

function useHeatmap(id: string, archiveId: string | null, live: boolean) {
  const [heat, setHeat] = useState<{
    cols: number;
    rows: number;
    grid: number[][];
    seconds: number;
  } | null>(null);
  useEffect(() => {
    setHeat(null);
    if (!id) return;
    let alive = true;
    const q = archiveId ? `?match=${encodeURIComponent(archiveId)}` : "";
    const load = () =>
      fetch(`/api/heatmap/${encodeURIComponent(id)}${q}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && setHeat(d && d.seconds > 0 ? d : null))
        .catch(() => undefined);
    load();
    const t = live ? window.setInterval(load, 20000) : undefined;
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [id, archiveId, live]);
  return heat;
}

function usePlayerStats(id: string, live: boolean): PlayerStats | null {
  const [p, setP] = useState<PlayerStats | null>(null);
  useEffect(() => {
    setP(null);
    if (!id || !live) return;
    let alive = true;
    const load = () =>
      fetch(`/api/players/${encodeURIComponent(id)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && setP(d && !d.error ? d : null))
        .catch(() => undefined);
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [id, live]);
  return p;
}

export default function App() {
  const { state, start, control, openArchive, backToLive } = useMatch();
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [tab, setTab] = useState<Tab>("live");
  const [term, setTerm] = useState<string | null>(null);
  const [lowerThird, setLowerThird] = useState<Overlay | null>(null);
  const [callout, setCallout] = useState<Overlay | null>(null);
  const seen = useRef(0);
  const timers = useRef<{ lt?: number; co?: number }>({});
  const viewing = state.viewing;
  const replay = useReplay(state.archiveId, !!viewing);
  const liveStats = usePlayerStats(
    prefs.playerCam,
    !viewing && !!state.metadata,
  );
  const heat = useHeatmap(
    prefs.playerCam,
    viewing ? viewing.id : null,
    !viewing && state.running,
  );
  const camEvents = state.events.filter(
    (e) =>
      prefs.playerCam &&
      e.player &&
      e.player === playerName(state.metadata, prefs.playerCam),
  );
  const camStats = viewing
    ? ((state.players[prefs.playerCam] as PlayerStats | undefined) ?? null)
    : liveStats;

  const set = useCallback((p: Partial<Prefs>) => {
    setPrefs((cur) => {
      const next = { ...cur, ...p };
      try {
        localStorage.setItem("gallery-prefs", JSON.stringify(next));
      } catch {
        /* storage unavailable: preferences last for this visit */
      }
      return next;
    });
  }, []);

  const clearGraphics = useCallback(() => {
    window.clearTimeout(timers.current.lt);
    window.clearTimeout(timers.current.co);
    setLowerThird(null);
    setCallout(null);
  }, []);

  // New narrative overlays become a broadcast lower-third (and, with the voice on, are read aloud);
  // block shifts are drawn on the pitch. Timers live in a ref so later overlays never cancel them.
  useEffect(() => {
    if (state.overlays.length < seen.current) seen.current = 0;
    const fresh = state.overlays.slice(seen.current);
    seen.current = state.overlays.length;
    if (viewing) return;
    const narrative = fresh.filter((o) => NARRATIVE.has(o.kind));
    if (!narrative.length) return;
    const top = [...narrative].sort((a, b) => b.priority - a.priority)[0];
    setLowerThird(top);
    window.clearTimeout(timers.current.lt);
    timers.current.lt = window.setTimeout(
      () => setLowerThird(null),
      LOWER_THIRD_MS,
    );
    const shape = narrative.find((o) =>
      o.evidence.some((e) => e.metric === "defensive_line_m"),
    );
    if (shape) {
      setCallout(shape);
      window.clearTimeout(timers.current.co);
      timers.current.co = window.setTimeout(
        () => setCallout(null),
        LOWER_THIRD_MS + 4000,
      );
    }
    if (prefs.voice && !replay.active) {
      const v = pickVariant(top, prefs);
      say(
        `${v.headline}. ${v.body ?? ""}`,
        top.variants[prefs.language] ? prefs.language : "en",
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.overlays]);

  useEffect(() => () => clearGraphics(), [clearGraphics]);

  useEffect(() => {
    if (state.recap && !viewing) setTab((t) => (t === "live" ? "recap" : t));
  }, [state.recap, viewing]);

  useEffect(() => {
    document.documentElement.lang = prefs.language;
  }, [prefs.language]);

  const kickoff = (
    seed: number,
    speed: number,
    source: "local" | "eventhub" = "local",
    brief = "",
  ) => {
    seen.current = 0;
    clearGraphics();
    replay.stop();
    stopSpeaking();
    setTab("live");
    start(seed, speed, source, brief);
  };

  const open = async (id: string) => {
    try {
      clearGraphics();
      replay.stop();
      stopSpeaking();
      await openArchive(id);
      setTab("recap");
    } catch (e) {
      window.alert(
        e instanceof Error ? e.message : "Couldn't open that match.",
      );
    }
  };

  const leaveArchive = async () => {
    replay.stop();
    stopSpeaking();
    await backToLive();
    setTab("live");
  };

  const showMe = async (o: Overlay) => {
    if (replay.active?.overlay_id === o.overlay_id) {
      replay.stop();
      return;
    }
    stopSpeaking();
    setTab("live");
    const finished = await replay.play(o);
    // hold the last frame for a beat, then cut back (unless the viewer already picked another moment)
    if (finished) window.setTimeout(() => replay.stopIf(o.overlay_id), 2000);
  };

  const meta = state.metadata;
  const status = state.status;
  const finishing = status.phase === "finishing";
  const started =
    !!viewing || state.running || !!state.frame || state.overlays.length > 0;

  if (!started) {
    return (
      <main className="shell kickoff-shell">
        <Kickoff onStart={kickoff} onOpenArchive={open} />
        {!state.connected && (
          <p className="conn">Connecting to the match room…</p>
        )}
      </main>
    );
  }

  const clock = viewing
    ? status.ended === "stopped"
      ? `${state.minute}'`
      : "FT"
    : !state.running
      ? finishing
        ? "FT…"
        : status.ended === "stopped"
          ? `${state.minute}' ■`
          : "FT"
      : status.phase === "half_time"
        ? "HT"
        : status.paused
          ? `${state.minute}' ❚❚`
          : `${state.minute}'`;

  const pitchFrame = replay.active
    ? replay.frame
    : viewing
      ? null
      : state.frame;
  const replayLabel = replay.active ? `${replay.active.minute}'` : null;

  return (
    <main className={`shell audience-${prefs.audience}`}>
      {viewing && (
        <div className="archive-banner" role="status">
          <span>
            <strong>Archived match</strong> · {viewing.title} ·{" "}
            {new Date(viewing.startedAt * 1000).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
            {state.liveStatus?.running ? " · a live match is on now" : ""}
          </span>
          <button className="chip" onClick={leaveArchive}>
            {state.liveStatus?.running ? "Back to the live match" : "Close"}
          </button>
        </div>
      )}
      <header className="topbar">
        <div className="scorebug" aria-label="Score">
          <span className="team home">{meta?.home.short_name ?? "Home"}</span>
          <span className="score">
            {state.score.home}
            <span className="dash">–</span>
            {state.score.away}
          </span>
          <span className="team away">{meta?.away.short_name ?? "Away"}</span>
          <span className={`clock ${status.paused ? "paused" : ""}`}>
            {clock}
          </span>
        </div>
        <nav className="tabs" aria-label="Views">
          <button aria-pressed={tab === "live"} onClick={() => setTab("live")}>
            {viewing ? "Moments" : "Live"}
          </button>
          <button
            aria-pressed={tab === "coach"}
            onClick={() => setTab("coach")}
          >
            Coach
            {Object.keys(state.coach).length
              ? ` (${Object.keys(state.coach).length})`
              : ""}
          </button>
          <button
            aria-pressed={tab === "producer"}
            onClick={() => setTab("producer")}
          >
            Producer
          </button>
          <button
            aria-pressed={tab === "recap"}
            disabled={!state.recap}
            onClick={() => setTab("recap")}
          >
            Recap
          </button>
          <button
            aria-pressed={tab === "matches"}
            onClick={() => setTab("matches")}
          >
            Matches
          </button>
          {!viewing && state.running && status.can_pause && (
            <button
              className="control"
              disabled={status.phase === "half_time"}
              onClick={() => control(status.paused ? "resume" : "pause")}
            >
              {status.paused ? "▶ Resume" : "❚❚ Pause"}
            </button>
          )}
          {!viewing && state.running && (
            <button
              className="control danger"
              onClick={() => {
                if (
                  window.confirm(
                    "End the match now? The crew writes a recap of the match so far and saves it.",
                  )
                )
                  control("end");
              }}
            >
              ■ End match
            </button>
          )}
          {!viewing && !state.running && (
            <button
              className="primary"
              disabled={finishing}
              onClick={() => kickoff(Math.floor(Math.random() * 9000) + 1, 20)}
            >
              {finishing ? "Writing recap…" : "New match"}
            </button>
          )}
        </nav>
        <Controls
          prefs={prefs}
          set={set}
          meta={meta}
          languages={state.languages}
          tab={tab}
          archived={!!viewing}
        />
        {state.scenario?.storyline && (
          <p className="storyline">Storyline: {state.scenario.storyline}</p>
        )}
        {!viewing && status.phase === "half_time" && (
          <p className="ht-note" role="status">
            Half-time. The coach analysts are writing their reports; play
            restarts when they're ready.
          </p>
        )}
      </header>

      {tab === "live" && (
        <div className="stage">
          <div className="stage-main">
            <Pitch
              frame={pitchFrame}
              meta={meta}
              prefs={prefs}
              lowerThird={replay.active ?? lowerThird}
              shapeCallout={
                replay.active
                  ? replay.active.evidence.some(
                      (e) => e.metric === "defensive_line_m",
                    )
                    ? replay.active
                    : null
                  : callout
              }
              replayLabel={replayLabel}
              onExitReplay={replay.active ? replay.stop : undefined}
              exitLabel={viewing ? "Close replay" : "Back to live"}
              camStats={camStats}
              heat={replay.active ? null : heat}
              heatLabel={
                meta && prefs.playerCam
                  ? meta.home.players.some((p) => p.id === prefs.playerCam)
                    ? `${meta.home.short_name} attack →`
                    : `← ${meta.away.short_name} attack`
                  : undefined
              }
              emptyCompact={!!heat}
              onToggle3d={() => set({ view3d: !prefs.view3d })}
              emptyText={
                viewing
                  ? heat
                    ? `${playerName(meta, prefs.playerCam)}'s heatmap for the whole match. Press “Show me” on a moment to replay it.`
                    : "Press “Show me” on any moment to replay it on the pitch, or pick a player to see their heatmap."
                  : !state.running && meta
                    ? heat
                      ? `${playerName(meta, prefs.playerCam)}'s heatmap for the whole match. Press “Show me” on a moment to replay it.`
                      : "Full time. Press “Show me” on any moment to replay it on the pitch."
                    : undefined
              }
            />
            {!viewing && (
              <Meters
                meters={state.meters}
                meta={meta}
                teams={state.teams}
                winProb={state.winProb}
                focus={prefs.focus}
                analyst={prefs.audience === "analyst"}
              />
            )}
            {(prefs.focus === "all" || viewing) && (
              <StoryChart
                history={state.history}
                events={state.events}
                overlays={state.overlays}
                meta={meta}
                compact
              />
            )}
            <TeamStats teams={state.teams} meta={meta} final={!state.running} />
          </div>
          <aside className="stage-side" aria-label="Insights">
            {!viewing && (
              <AskPundit prefs={prefs} onTerm={setTerm} enabled={!!meta} />
            )}
            {prefs.playerCam && (
              <PlayerCard
                p={camStats as Record<string, any> | null}
                title={
                  viewing ? "Full match" : state.running ? "Live" : "Full match"
                }
                events={camEvents}
                heatSeconds={heat?.seconds}
                missing={
                  viewing && !camStats
                    ? "Detailed stats weren't saved for this older match; the heatmap and moments still work."
                    : undefined
                }
              >
                <PlayerReportBox
                  playerId={prefs.playerCam}
                  archiveId={viewing ? viewing.id : null}
                  language={prefs.language}
                />
              </PlayerCard>
            )}
            <Feed
              overlays={state.overlays}
              meta={meta}
              prefs={prefs}
              onTerm={setTerm}
              onReplay={showMe}
              replaying={replay.active?.overlay_id ?? null}
              onClearPlayer={() => set({ playerCam: "" })}
            />
          </aside>
        </div>
      )}
      {tab === "coach" && (
        <CoachView
          coach={state.coach}
          meta={meta}
          prefs={prefs}
          running={state.running}
          archived={!!viewing}
        />
      )}
      {tab === "producer" && <Producer trace={state.trace} />}
      {tab === "recap" && state.recap && (
        <RecapView
          recap={state.recap}
          language={prefs.language}
          highlights={
            <HighlightsReel
              overlays={state.overlays}
              meta={meta}
              prefs={prefs}
              archiveId={state.archiveId}
              viewingArchive={!!viewing}
            />
          }
          chart={
            <>
              <StoryChart
                history={state.history}
                events={state.events}
                overlays={state.overlays}
                meta={meta}
              />
              <TeamStats teams={state.teams} meta={meta} final />
            </>
          }
        />
      )}
      {tab === "matches" && (
        <div className="matches-view">
          <h2>Past matches</h2>
          <ArchiveList
            onOpen={open}
            onRerun={
              !(viewing ? state.liveStatus?.running : state.running)
                ? (seed) => kickoff(seed, 20)
                : undefined
            }
          />
        </div>
      )}
      {term && <GlossaryDialog term={term} onClose={() => setTerm(null)} />}
      <footer className="foot">
        Synthetic data. Clubs and players are fictional.
      </footer>
    </main>
  );
}
