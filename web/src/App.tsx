import { useCallback, useEffect, useRef, useState } from "react";
import { Feed } from "./Feed";
import { Meters } from "./Meters";
import { Controls, GlossaryDialog, Kickoff, PlayerCard, Producer, RecapView } from "./Panels";
import { AskPundit, CoachView, StoryChart } from "./Extras";
import { Pitch } from "./Pitch";
import { NARRATIVE } from "./lib";
import type { Overlay, Prefs } from "./types";
import { useMatch } from "./useMatch";

const DEFAULT_PREFS: Prefs = { audience: "casual", lens: "neutral", language: "en", playerCam: "", focus: "all" };
const LOWER_THIRD_MS = 9000;

function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem("gallery-prefs") ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

type Tab = "live" | "coach" | "producer" | "recap";

export default function App() {
  const { state, start } = useMatch();
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [tab, setTab] = useState<Tab>("live");
  const [term, setTerm] = useState<string | null>(null);
  const [lowerThird, setLowerThird] = useState<Overlay | null>(null);
  const [callout, setCallout] = useState<Overlay | null>(null);
  const seen = useRef(0);

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

  // New narrative overlays become a broadcast lower-third; block shifts are drawn on the pitch.
  useEffect(() => {
    const fresh = state.overlays.slice(seen.current);
    seen.current = state.overlays.length;
    const narrative = fresh.filter((o) => NARRATIVE.has(o.kind));
    if (!narrative.length) return;
    const top = narrative.sort((a, b) => b.priority - a.priority)[0];
    setLowerThird(top);
    const t1 = window.setTimeout(() => setLowerThird((cur) => (cur === top ? null : cur)), LOWER_THIRD_MS);
    const shape = narrative.find((o) => o.evidence.some((e) => e.metric === "defensive_line_m"));
    let t2: number | undefined;
    if (shape) {
      setCallout(shape);
      t2 = window.setTimeout(() => setCallout((cur) => (cur === shape ? null : cur)), LOWER_THIRD_MS + 4000);
    }
    return () => {
      window.clearTimeout(t1);
      if (t2) window.clearTimeout(t2);
    };
  }, [state.overlays]);

  useEffect(() => {
    if (state.recap) setTab((t) => (t === "live" ? "recap" : t));
  }, [state.recap]);

  useEffect(() => {
    document.documentElement.lang = prefs.language;
  }, [prefs.language]);

  const meta = state.metadata;
  const started = state.running || !!state.frame || state.overlays.length > 0;

  if (!started) {
    return (
      <main className="shell kickoff-shell">
        <Kickoff
          onStart={(seed, speed, source, brief) => {
            seen.current = 0;
            setTab("live");
            start(seed, speed, source, brief);
          }}
        />
        {!state.connected && <p className="conn">Connecting to the match room…</p>}
      </main>
    );
  }

  return (
    <main className={`shell audience-${prefs.audience}`}>
      <header className="topbar">
        <div className="scorebug" aria-label="Score">
          <span className="team home">{meta?.home.short_name ?? "Home"}</span>
          <span className="score">
            {state.score.home}
            <span className="dash">–</span>
            {state.score.away}
          </span>
          <span className="team away">{meta?.away.short_name ?? "Away"}</span>
          <span className="clock">{state.running ? `${state.minute}'` : "FT"}</span>
        </div>
        <nav className="tabs" aria-label="Views">
          <button aria-pressed={tab === "live"} onClick={() => setTab("live")}>
            Live
          </button>
          <button aria-pressed={tab === "coach"} onClick={() => setTab("coach")}>
            Coach{Object.keys(state.coach).length ? ` (${Object.keys(state.coach).length})` : ""}
          </button>
          <button aria-pressed={tab === "producer"} onClick={() => setTab("producer")}>
            Producer
          </button>
          <button aria-pressed={tab === "recap"} disabled={!state.recap} onClick={() => setTab("recap")}>
            Recap
          </button>
          {!state.running && (
            <button
              className="primary"
              onClick={() => {
                seen.current = 0;
                setTab("live");
                start(Math.floor(Math.random() * 9000) + 1, 20);
              }}
            >
              New match
            </button>
          )}
        </nav>
        <Controls prefs={prefs} set={set} meta={meta} languages={state.languages} />
        {state.scenario?.storyline && <p className="storyline">Storyline: {state.scenario.storyline}</p>}
      </header>

      {tab === "live" && (
        <div className="stage">
          <div className="stage-main">
            <Pitch frame={state.frame} meta={meta} prefs={prefs} lowerThird={lowerThird} shapeCallout={callout} />
            <Meters
              meters={state.meters}
              meta={meta}
              teams={state.teams}
              winProb={state.winProb}
              focus={prefs.focus}
              analyst={prefs.audience === "analyst"}
            />
            {prefs.focus === "all" && (
              <StoryChart history={state.history} events={state.events} overlays={state.overlays} meta={meta} compact />
            )}
          </div>
          <aside className="stage-side" aria-label="Insights">
            <AskPundit prefs={prefs} onTerm={setTerm} enabled={!!meta} />
            {prefs.playerCam && <PlayerCard id={prefs.playerCam} />}
            <Feed overlays={state.overlays} meta={meta} prefs={prefs} onTerm={setTerm} />
          </aside>
        </div>
      )}
      {tab === "coach" && <CoachView coach={state.coach} meta={meta} prefs={prefs} running={state.running} />}
      {tab === "producer" && <Producer trace={state.trace} />}
      {tab === "recap" && state.recap && (
        <RecapView
          recap={state.recap}
          language={prefs.language}
          chart={<StoryChart history={state.history} events={state.events} overlays={state.overlays} meta={meta} />}
        />
      )}
      {term && <GlossaryDialog term={term} onClose={() => setTerm(null)} />}
      <footer className="foot">Synthetic data. Clubs and players are fictional.</footer>
    </main>
  );
}
