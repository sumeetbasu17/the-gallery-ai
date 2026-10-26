import React, { useEffect, useState } from "react";
import type {
  ArchiveSummary,
  Metadata,
  Prefs,
  Recap,
  TraceStep,
} from "./types";
import { AGENT_NAMES, LANG_NAMES } from "./lib";
import { onSpeaking, say, stopSpeaking } from "./audio";
import { MicButton } from "./Mic";

/* ------------------------------------------------------------------ Controls */
/**
 * Viewing preferences. Only the ones that change the current screen are shown:
 * the live view uses all of them, the recap only the language, coach / producer / matches none.
 */
export function Controls({
  prefs,
  set,
  meta,
  languages,
  tab,
  archived,
}: {
  prefs: Prefs;
  set: (p: Partial<Prefs>) => void;
  meta: Metadata | null;
  languages: string[];
  tab: string;
  archived: boolean;
}) {
  const players = meta ? [...meta.home.players, ...meta.away.players] : [];
  if (tab !== "live" && tab !== "recap") return null;
  const live = tab === "live";
  return (
    <div className="controls" role="group" aria-label="Viewing preferences">
      {live && (
        <>
          <div className="seg" role="radiogroup" aria-label="Viewing mode">
            {(["casual", "analyst"] as const).map((a) => (
              <button
                key={a}
                role="radio"
                aria-checked={prefs.audience === a}
                onClick={() => set({ audience: a })}
              >
                {a === "casual" ? "Casual" : "Analyst"}
              </button>
            ))}
          </div>
          <label>
            <span>Support</span>
            <select
              value={prefs.lens}
              onChange={(e) => set({ lens: e.target.value as Prefs["lens"] })}
            >
              <option value="neutral">Neutral</option>
              <option value="home">{meta?.home.name ?? "Home"}</option>
              <option value="away">{meta?.away.name ?? "Away"}</option>
            </select>
          </label>
          <label>
            <span>Follow player</span>
            <select
              value={prefs.playerCam}
              onChange={(e) => set({ playerCam: e.target.value })}
            >
              <option value="">Off</option>
              {players.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.number} {p.name}
                </option>
              ))}
            </select>
          </label>

          {!archived && (
            <label>
              <span>Focus</span>
              <select
                value={prefs.focus}
                onChange={(e) =>
                  set({ focus: e.target.value as Prefs["focus"] })
                }
              >
                <option value="all">All meters</option>
                <option value="control">Control vs chaos</option>
                <option value="pressure">Pressure</option>
                <option value="rhythm">Rhythm</option>
              </select>
            </label>
          )}
        </>
      )}
      <label>
        <span>Language</span>
        <select
          value={prefs.language}
          onChange={(e) => set({ language: e.target.value })}
        >
          {languages.map((l) => (
            <option key={l} value={l}>
              {LANG_NAMES[l] ?? l}
            </option>
          ))}
        </select>
      </label>
      {live && !archived && (
        <label
          className="check voice-toggle"
          title="Read each new insight aloud in your language"
        >
          <input
            type="checkbox"
            checked={prefs.voice}
            onChange={(e) => {
              if (!e.target.checked) stopSpeaking();
              set({ voice: e.target.checked });
            }}
          />
          <span>Commentary voice</span>
        </label>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Player cam */
export function PlayerCard({
  p,
  title,
  events = [],
  heatSeconds,
  missing,
  children,
}: {
  p: Record<string, any> | null;
  title?: string;
  events?: {
    type: string;
    minute: number;
    detail?: Record<string, unknown> | null;
  }[];
  heatSeconds?: number;
  missing?: string;
  children?: React.ReactNode;
}) {
  if (missing) return <p className="feed-hint">{missing}</p>;
  if (!p || p.error) return null;
  const label: Record<string, string> = {
    goal: "Goal",
    card: "Yellow card",
    substitution: "Substitution",
  };
  return (
    <aside className="player-card" aria-label={`Player cam: ${p.player}`}>
      <h3>
        {p.player} {title && <span className="card-kicker">{title}</span>}
      </h3>
      {p.team && <p className="muted card-team">{p.team}</p>}
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
        <dt>Shots</dt>
        <dd>{p.shots}</dd>
        <dt>Shots on target</dt>
        <dd>{p.shots_on_target ?? "–"}</dd>
        <dt>Goals / xG</dt>
        <dd>
          {p.goals ?? 0} / {p.xg}
        </dd>
        {heatSeconds ? (
          <>
            <dt>Minutes on the pitch</dt>
            <dd>{Math.round(heatSeconds / 60)}</dd>
          </>
        ) : null}
      </dl>
      {events.length > 0 && (
        <ul className="card-events">
          {events.map((e, i) => (
            <li key={i}>
              <span className="num">{e.minute}'</span>{" "}
              {e.type === "card" && e.detail?.card === "red"
                ? "Red card"
                : (label[e.type] ?? e.type)}
            </li>
          ))}
        </ul>
      )}
      {heatSeconds ? (
        <p className="muted card-note">
          The shaded squares on the pitch show where they've played.
        </p>
      ) : null}
      {children}
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
          <Node
            id="tactical_analyst"
            sub={`${count("tactical_analyst")} calls · MCP tools`}
          />
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
        The gallery behind the broadcast: every agent hop, live. Rejections show
        the Fact-Checker sending a line back; errors show a model call failing
        and the crew recovering.
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
            <span className="step-agent">
              {AGENT_NAMES[s.agent] ?? s.agent}
            </span>
            <span className="step-action">{s.action}</span>
            <span className="num">{s.ms} ms</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* --------------------------------------------------------------------- Recap */
export function RecapView({
  recap,
  language,
  chart,
  highlights,
}: {
  recap: Recap;
  language: string;
  chart: React.ReactNode;
  highlights?: React.ReactNode;
}) {
  const [audio, setAudio] = useState("");
  const [playing, setPlaying] = useState(false);

  useEffect(() => () => stopSpeaking(), []);
  const r = recap.recap;
  const translated = recap.translations?.[language];
  const tr = translated ??
    recap.translations?.en ?? {
      headline: r.headline,
      paragraphs: r.paragraphs,
    };
  const text = [tr.headline, ...tr.paragraphs].join(" ");
  const voiceLang = translated ? language : "en";
  useEffect(
    () =>
      onSpeaking((on, playingText) => setPlaying(on && playingText === text)),
    [text],
  );
  return (
    <article className="recap">
      {recap.stopped_at != null && (
        <p className="stopped-note">
          Ended early by the producer at {recap.stopped_at}'
        </p>
      )}
      <h2>{tr.headline}</h2>
      {language !== "en" && !translated && (
        <p className="muted">
          This recap isn't available in {LANG_NAMES[language] ?? language} yet;
          showing English.
        </p>
      )}
      <div className="recap-actions">
        <button
          className="primary"
          onClick={async () => {
            if (playing) {
              stopSpeaking();
              setAudio("");
              return;
            }
            setAudio("Loading audio…");
            await say(text, voiceLang, (how) =>
              setAudio(
                how === "azure"
                  ? `Voice: Azure AI Speech (${LANG_NAMES[voiceLang]})`
                  : `Voice: your browser (${LANG_NAMES[voiceLang]})`,
              ),
            );
          }}
        >
          {playing ? "■ Stop audio" : "▶ Play audio recap"}
        </button>
        {audio && <span className="audio-note">{audio}</span>}
      </div>
      {highlights}
      {chart}
      {tr.paragraphs.map((p, i) => (
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
          <strong>Player of the match: {r.player_of_the_match}.</strong>{" "}
          {r.player_of_the_match_reason}
        </p>
      )}
    </article>
  );
}

/* ------------------------------------------------------------------ Glossary */
export function GlossaryDialog({
  term,
  onClose,
}: {
  term: string;
  onClose: () => void;
}) {
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
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="gl-title"
        onClick={(e) => e.stopPropagation()}
      >
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

/* ------------------------------------------------------------------- Archive */
const PAGE = 8;

export function ArchiveList({
  onOpen,
  onRerun,
  compact,
}: {
  onOpen: (id: string) => void;
  onRerun?: (seed: number) => void;
  compact?: boolean;
}) {
  const [items, setItems] = useState<ArchiveSummary[]>([]);
  const [cursors, setCursors] = useState<string[]>([""]); // cursor for each page we've visited
  const [page, setPage] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async (p: number, cursor: string) => {
    setLoading(true);
    try {
      const r = await fetch(
        `/api/matches?limit=${compact ? 4 : PAGE}&cursor=${encodeURIComponent(cursor)}`,
      );
      const d = await r.json();
      setItems(d.items ?? []);
      setNext(d.next ?? null);
      setTotal(d.total ?? null);
      setError(d.error ?? "");
      setPage(p);
    } catch {
      setError("The match archive is unavailable right now.");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load(0, "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const remove = async (id: string) => {
    if (!window.confirm("Delete this match from the archive?")) return;
    await fetch(`/api/matches/${encodeURIComponent(id)}`, { method: "DELETE" });
    load(page, cursors[page]);
  };

  if (loading && !items.length)
    return <p className="muted">Loading past matches…</p>;
  if (error) return <p className="field-error">{error}</p>;
  if (!items.length)
    return compact ? null : (
      <p className="muted">
        No matches yet. Every match you kick off is saved here when it ends.
      </p>
    );

  return (
    <section
      className={`archive ${compact ? "compact" : ""}`}
      aria-label="Past matches"
    >
      {compact && <h2>Past matches</h2>}
      <ul>
        {items.map((m) => (
          <li key={m.id} className="archive-row">
            <div>
              <strong className="archive-title">{m.title}</strong>
              <span
                className={m.ended === "stopped" ? "stopped-chip" : "ft-chip"}
              >
                {m.ended === "stopped" ? `Stopped ${m.minute}'` : "FT"}
              </span>
              <p className="muted">
                {new Date(m.ended_at * 1000).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}{" "}
                · seed {m.seed} · {m.insights} insights
                {m.scenario_title ? ` · ${m.scenario_title}` : ""}
              </p>
              {!compact && m.headline && (
                <p className="archive-headline">{m.headline}</p>
              )}
            </div>
            <div className="archive-actions">
              <button className="primary" onClick={() => onOpen(m.id)}>
                Open
              </button>
              {onRerun && !compact && (
                <button
                  className="chip"
                  onClick={() => onRerun(m.seed)}
                  title="Kick off the same match again (same seed)"
                >
                  Re-run
                </button>
              )}
              {!compact && (
                <button className="chip ghost" onClick={() => remove(m.id)}>
                  Delete
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <nav className="pager" aria-label="Pages">
        <button
          className="chip"
          disabled={page === 0 || loading}
          onClick={() => load(page - 1, cursors[page - 1])}
        >
          ← Newer
        </button>
        <span className="muted">
          Page {page + 1}
          {total != null
            ? ` of ${Math.max(1, Math.ceil(total / (compact ? 4 : PAGE)))}`
            : ""}
        </span>
        <button
          className="chip"
          disabled={!next || loading}
          onClick={() => {
            const c = [...cursors.slice(0, page + 1), next as string];
            setCursors(c);
            load(page + 1, next as string);
          }}
        >
          Older →
        </button>
      </nav>
      {!compact && (
        <p className="muted small">
          The newest 50 matches are kept. Each one stores every insight, coach
          report, recap and chart; the pitch replays are rebuilt from the match
          seed, so no video is stored.
        </p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------- Kickoff */
export function Kickoff({
  onStart,
  onOpenArchive,
  onCancel,
  language = "en",
}: {
  onCancel?: () => void;
  language?: string;
  onStart: (
    seed: number,
    speed: number,
    source: "local" | "eventhub",
    brief: string,
  ) => void;
  onOpenArchive: (id: string) => void;
}) {
  const [brief, setBrief] = useState("");
  const [seed, setSeed] = useState(() =>
    onCancel ? Math.floor(Math.random() * 9000) + 1 : 7,
  );
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
      {onCancel && (
        <button className="chip back-link" onClick={onCancel}>
          ← Back to the match
        </button>
      )}
      <h1>The Gallery</h1>
      <p className="lede">
        A crew of AI agents watches every pass, works out what matters, checks
        its facts, and tells the story your way: in your language, for your
        club, at your level.
      </p>
      <p className="muted">
        Riverside Athletic v Northgate United, a synthetic match generated live.
        Clubs and players are fictional.
      </p>
      <div className="brief">
        <label htmlFor="brief-text">
          Storyline (optional). The Scenario Writer agent turns it into the
          match: each team's tactics, the final score and any red cards. It
          doesn't script who scores or when.
        </label>
        <div className="brief-row">
          <textarea
            id="brief-text"
            rows={2}
            maxLength={400}
            value={brief}
            placeholder="A 5-4 thriller: Northgate press high early, a first-half red card for Riverside, then Northgate sit deep after the hour."
            onChange={(e) => setBrief(e.target.value)}
          />
          <MicButton
            language={language}
            value={brief}
            label="Speak"
            onText={setBrief}
          />
        </div>
      </div>
      <div className="kickoff-form">
        <label>
          <span>Match seed</span>
          <input
            type="number"
            min={1}
            max={9999}
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value) || 1)}
          />
        </label>
        <label>
          <span>Speed</span>
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          >
            <option value={10}>10× (9 minutes)</option>
            <option value={20}>20× (about 5 minutes)</option>
            <option value={40}>40× (about 2½ minutes)</option>
          </select>
        </label>
        {hubAvailable && (
          <label className="check">
            <input
              type="checkbox"
              checked={hub}
              onChange={(e) => setHub(e.target.checked)}
            />
            <span>Stream through Azure Event Hubs</span>
          </label>
        )}
        <button
          className="primary big"
          onClick={() =>
            onStart(seed, speed, hub ? "eventhub" : "local", brief)
          }
        >
          Kick off
        </button>
      </div>
      <ArchiveList compact onOpen={onOpenArchive} />
    </div>
  );
}
