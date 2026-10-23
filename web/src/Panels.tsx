import { useEffect, useState } from "react";
import type { Metadata, Prefs, Recap, TraceStep } from "./types";
import { AGENT_NAMES, LANG_NAMES, speak } from "./lib";

/* ------------------------------------------------------------------ Controls */
export function Controls({ prefs, set, meta, languages }: {
  prefs: Prefs;
  set: (p: Partial<Prefs>) => void;
  meta: Metadata | null;
  languages: string[];
}) {
  const players = meta ? [...meta.home.players, ...meta.away.players] : [];
  return (
    <div className="controls" role="group" aria-label="Viewing preferences">
      <div className="seg" role="radiogroup" aria-label="Viewing mode">
        {(["casual", "analyst"] as const).map((a) => (
          <button key={a} role="radio" aria-checked={prefs.audience === a} onClick={() => set({ audience: a })}>
            {a === "casual" ? "Casual" : "Analyst"}
          </button>
        ))}
      </div>
      <label>
        <span>Support</span>
        <select value={prefs.lens} onChange={(e) => set({ lens: e.target.value as Prefs["lens"] })}>
          <option value="neutral">Neutral</option>
          <option value="home">{meta?.home.name ?? "Home"}</option>
          <option value="away">{meta?.away.name ?? "Away"}</option>
        </select>
      </label>
      <label>
        <span>Player cam</span>
        <select value={prefs.playerCam} onChange={(e) => set({ playerCam: e.target.value })}>
          <option value="">Off</option>
          {players.map((p) => (
            <option key={p.id} value={p.id}>
              {p.number} {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Focus</span>
        <select value={prefs.focus} onChange={(e) => set({ focus: e.target.value as Prefs["focus"] })}>
          <option value="all">All meters</option>
          <option value="control">Control vs chaos</option>
          <option value="pressure">Pressure</option>
          <option value="rhythm">Rhythm</option>
        </select>
      </label>
      <label>
        <span>Language</span>
        <select value={prefs.language} onChange={(e) => set({ language: e.target.value })}>
          {languages.map((l) => (
            <option key={l} value={l}>
              {LANG_NAMES[l] ?? l}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/* ---------------------------------------------------------------- Player cam */
export function PlayerCard({ id }: { id: string }) {
  const [p, setP] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`/api/players/${encodeURIComponent(id)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && setP(d));
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [id]);
  if (!p || p.error) return null;
  return (
    <aside className="player-card" aria-label={`Player cam: ${p.player}`}>
      <h3>{p.player}</h3>
      <dl>
        <dt>Distance</dt>
        <dd>{p.distance_km} km</dd>
        <dt>Top speed</dt>
        <dd>{p.top_speed_kmh} km/h</dd>
        <dt>Sprints</dt>
        <dd>{p.sprints}</dd>
        <dt>Passes</dt>
        <dd>
          {p.passes}
          {p.pass_completion_pct != null && ` (${p.pass_completion_pct}%)`}
        </dd>
        <dt>Avg pass difficulty</dt>
        <dd>{p.avg_pass_difficulty ?? "–"}</dd>
        <dt>Shots / xG</dt>
        <dd>
          {p.shots} / {p.xg}
        </dd>
      </dl>
    </aside>
  );
}

/* ------------------------------------------------------------------ Producer */
export function Producer({ trace }: { trace: TraceStep[] }) {
  const recent = trace.slice(-60).reverse();
  const byAgent = new Map<string, { n: number; ms: number; err: number }>();
  for (const s of trace) {
    const a = byAgent.get(s.agent) ?? { n: 0, ms: 0, err: 0 };
    a.n += 1;
    a.ms += s.ms;
    a.err += s.status === "error" ? 1 : 0;
    byAgent.set(s.agent, a);
  }
  const last = trace[trace.length - 1];
  const rejections = trace.filter((s) => s.status === "rejected").length;
  const fallbacks = trace.filter((s) => s.status === "fallback").length;
  const count = (a: string) => byAgent.get(a)?.n ?? 0;
  const Node = ({ id, sub }: { id: string; sub?: string }) => (
    <div className={`node ${last?.agent === id ? "active" : ""}`}>
      <strong>{AGENT_NAMES[id] ?? id}</strong>
      <span>{sub ?? `${count(id)} calls`}</span>
    </div>
  );
  return (
    <div className="producer">
      <div className="flow" aria-label="How a moment travels through the crew">
        <Node id="stats_engine" sub="detects signals" />
        <span className="arrow" aria-hidden="true" />
        <Node id="match_director" sub="decides what airs" />
        <span className="arrow" aria-hidden="true" />
        <div className="parallel">
          <Node id="tactical_analyst" sub={`${count("tactical_analyst")} calls · MCP tools`} />
          <Node id="moment_judge" />
        </div>
        <span className="arrow" aria-hidden="true" />
        <div className="loop">
          <Node id="storyteller" />
          <span className="loop-label">{rejections} sent back</span>
          <Node id="fact_checker" sub={`${count("fact_checker")} checks`} />
        </div>
        <span className="arrow" aria-hidden="true" />
        <Node id="fan_producer" sub={`${count("fan_producer")} versions`} />
        <span className="arrow" aria-hidden="true" />
        <div className="node screen">
          <strong>On screen</strong>
          <span>{fallbacks} template fallbacks</span>
        </div>
      </div>
      <p className="producer-intro">
        The gallery behind the broadcast: every agent hop, live. Rejections show the Fact-Checker sending a line back; errors
        show a model call failing and the crew recovering.
      </p>
      <table className="crew-table">
        <thead>
          <tr>
            <th scope="col">Agent</th>
            <th scope="col">Calls</th>
            <th scope="col">Avg ms</th>
            <th scope="col">Errors</th>
          </tr>
        </thead>
        <tbody>
          {[...byAgent.entries()].map(([agent, a]) => (
            <tr key={agent}>
              <td>{AGENT_NAMES[agent] ?? agent}</td>
              <td className="num">{a.n}</td>
              <td className="num">{a.n ? Math.round(a.ms / a.n) : 0}</td>
              <td className="num">{a.err}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ol className="talkback">
        {recent.map((s, i) => (
          <li key={i} className={`status-${s.status}`}>
            <span className="minute">{s.minute}'</span>
            <span className="step-agent">{AGENT_NAMES[s.agent] ?? s.agent}</span>
            <span className="step-action">{s.action}</span>
            <span className="num">{s.ms} ms</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* --------------------------------------------------------------------- Recap */
export function RecapView({ recap }: { recap: Recap }) {
  const r = recap.recap;
  const text = [r.headline, ...r.paragraphs].join(" ");
  return (
    <article className="recap">
      <h2>{r.headline}</h2>
      <button className="primary" onClick={() => speak(text, "en")}>
        Play audio recap
      </button>
      {r.paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
      {r.key_moments.length > 0 && (
        <>
          <h3>Key moments</h3>
          <ul>
            {r.key_moments.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}
      {r.player_of_the_match && (
        <p className="potm">
          <strong>Player of the match: {r.player_of_the_match}.</strong> {r.player_of_the_match_reason}
        </p>
      )}
    </article>
  );
}

/* ------------------------------------------------------------------ Glossary */
export function GlossaryDialog({ term, onClose }: { term: string; onClose: () => void }) {
  const [d, setD] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    fetch(`/api/glossary/${encodeURIComponent(term)}`)
      .then((r) => r.json())
      .then(setD);
  }, [term]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="gl-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="gl-title">{d?.term ?? term}</h2>
        {d?.definition && <p>{d.definition}</p>}
        {d?.how_we_measure && (
          <p className="muted">
            <strong>How we measure it:</strong> {d.how_we_measure}
          </p>
        )}
        {d?.live && (
          <div className="live-metric">
            <strong>In this match right now</strong>
            <ul>
              {Object.entries(d.live).map(([k, v]) => (
                <li key={k}>
                  {k}: <span className="num">{String(v)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <button className="primary" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- Kickoff */
export function Kickoff({ onStart }: {
  onStart: (seed: number, speed: number, source: "local" | "eventhub", brief: string) => void;
}) {
  const [brief, setBrief] = useState("");
  const [seed, setSeed] = useState(7);
  const [speed, setSpeed] = useState(20);
  const [hub, setHub] = useState(false);
  const [hubAvailable, setHubAvailable] = useState(false);
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((h) => {
        setHubAvailable(!!h.eventhub);
        setHub(!!h.eventhub);
      })
      .catch(() => undefined);
  }, []);
  return (
    <div className="kickoff">
      <h1>The Gallery</h1>
      <p className="lede">
        A crew of AI agents watches every pass, works out what matters, checks its facts, and tells the story your way: in
        your language, for your club, at your level.
      </p>
      <p className="muted">Riverside Athletic v Northgate United, a synthetic match generated live. Clubs and players are fictional.</p>
      <label className="brief">
        <span>Storyline (optional). The Scenario Writer agent turns it into the match.</span>
        <textarea
          rows={2}
          maxLength={400}
          value={brief}
          placeholder="Northgate press high early, then drop into a low block to protect a lead after the hour."
          onChange={(e) => setBrief(e.target.value)}
        />
      </label>
      <div className="kickoff-form">
        <label>
          <span>Match seed</span>
          <input type="number" min={1} max={9999} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 1)} />
        </label>
        <label>
          <span>Speed</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            <option value={10}>10× (9 minutes)</option>
            <option value={20}>20× (about 5 minutes)</option>
            <option value={40}>40× (about 2½ minutes)</option>
          </select>
        </label>
        {hubAvailable && (
          <label className="check">
            <input type="checkbox" checked={hub} onChange={(e) => setHub(e.target.checked)} />
            <span>Stream through Azure Event Hubs</span>
          </label>
        )}
        <button className="primary big" onClick={() => onStart(seed, speed, hub ? "eventhub" : "local", brief)}>
          Kick off
        </button>
      </div>
    </div>
  );
}
