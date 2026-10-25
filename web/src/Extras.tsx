import { useEffect, useState } from "react";
import type { CoachDoc, HistoryPoint, MatchEvent, Metadata, Overlay, Prefs, PunditReply } from "./types";
import { LANG_NAMES } from "./lib";
import { onSpeaking, say, stopSpeaking } from "./audio";

/* --------------------------------------------------------------- Ask the pundit */
const SUGGESTIONS: Record<string, string[]> = {
  en: ["Why is this game so open?", "Who has been the best passer?", "Is the press working?", "Who is more likely to win?"],
  hi: ["यह मैच इतना खुला क्यों है?", "सबसे अच्छा पासर कौन रहा है?", "क्या प्रेसिंग काम कर रही है?", "कौन जीत सकता है?"],
  es: ["¿Por qué el partido está tan abierto?", "¿Quién ha sido el mejor pasador?", "¿Está funcionando la presión?", "¿Quién tiene más opciones de ganar?"],
};

/** A small play/stop button for any text, in the viewer's language. */
export function ListenButton({ text, language, label = "Listen" }: { text: string; language: string; label?: string }) {
  const [mine, setMine] = useState(false);
  useEffect(() => onSpeaking((speaking) => !speaking && setMine(false)), []);
  return (
    <button
      type="button"
      className="listen"
      aria-pressed={mine}
      onClick={() => {
        if (mine) {
          stopSpeaking();
          setMine(false);
          return;
        }
        say(text, language);
        setMine(true);
      }}
    >
      {mine ? "■ Stop" : `▶ ${label}`}
    </button>
  );
}

export function AskPundit({ prefs, onTerm, enabled }: { prefs: Prefs; onTerm: (t: string) => void; enabled: boolean }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [replies, setReplies] = useState<PunditReply[]>([]);

  const ask = async (question: string) => {
    const text = question.trim();
    if (text.length < 3) {
      setError("Type a question about the match first.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: text, language: prefs.language }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error ?? "The pundit couldn't answer.");
      setReplies((cur) => [{ question: text, ...d }, ...cur].slice(0, 5));
      setQ("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The pundit couldn't answer. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="pundit" aria-label="Ask the pundit">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
      >
        <label htmlFor="pundit-q">Ask the pundit</label>
        <div className="pundit-row">
          <input
            id="pundit-q"
            value={q}
            maxLength={300}
            disabled={!enabled}
            placeholder={enabled ? "Why can't Riverside break them down?" : "Available once the match starts"}
            onChange={(e) => {
              setQ(e.target.value);
              setError("");
            }}
          />
          <button className="primary" disabled={busy || !enabled}>
            {busy ? "Thinking…" : "Ask"}
          </button>
        </div>
        {error && <p className="field-error">{error}</p>}
        {enabled && (
          <div className="chips">
            {(SUGGESTIONS[prefs.language] ?? SUGGESTIONS.en).map((s) => (
              <button type="button" key={s} className="chip" onClick={() => ask(s)} disabled={busy}>
                {s}
              </button>
            ))}
            {replies.length > 0 && (
              <button
                type="button"
                className="chip ghost"
                onClick={() => {
                  stopSpeaking();
                  setReplies([]);
                }}
              >
                Clear answers
              </button>
            )}
          </div>
        )}
      </form>
      {replies.map((r, i) => (
        <article key={`${r.question}-${i}`} className="reply">
          <p className="reply-q">{r.question}</p>
          <p>{r.answer}</p>
          <div className="insight-meta">
            {r.verified ? <span className="checked">Fact-checked</span> : <span className="unchecked">Unverified</span>}
            {r.minute != null && <span className="team-chip">at {r.minute}'</span>}
            <ListenButton text={r.answer} language={prefs.language} />
            {r.terms.map((t) => (
              <button key={t} className="term" onClick={() => onTerm(t)}>
                What's "{t}"?
              </button>
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}

/* --------------------------------------------------------------- Coach reports */
export function CoachView({ coach, meta, prefs, running, archived }: {
  coach: Record<string, CoachDoc>;
  meta: Metadata | null;
  prefs: Prefs;
  running: boolean;
  archived?: boolean;
}) {
  const [busy, setBusy] = useState<string>("");
  const order: ("home" | "away")[] = prefs.lens === "away" ? ["away", "home"] : ["home", "away"];
  const generate = async (side: string) => {
    setBusy(side);
    try {
      await fetch(`/api/coach/${side}`, { method: "POST" });
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="coach">
      <p className="producer-intro">
        A first-team analyst agent studies the match through the same tools and writes what's working, what isn't, and
        three changes for each club's staff. Reports arrive automatically at half-time; you can ask for a fresh one any
        time.
      </p>
      <div className="coach-grid">
        {order.map((side) => {
          const doc = coach[side];
          const team = side === "home" ? meta?.home : meta?.away;
          return (
            <article key={side} className={`coach-card side-${side}`}>
              <header>
                <h2>{team?.name ?? side}</h2>
                {!archived && (
                  <button className="chip" disabled={!!busy || !meta} onClick={() => generate(side)}>
                    {busy === side ? "Writing…" : doc ? "Refresh report" : running ? "Write report now" : "Write report"}
                  </button>
                )}
              </header>
              {!doc?.report && <p className="muted">{archived ? "No report for this match." : "No report yet. It arrives at half-time."}</p>}
              {doc?.report && (
                <>
                  <h3>{doc.report.headline}</h3>
                  <p className="muted coach-meta">
                    {doc.kind === "half_time" ? "Half-time report" : `Report at ${doc.minute}'`} ·{" "}
                    {doc.verified ? (
                      <span className="checked">Numbers fact-checked</span>
                    ) : (
                      <span className="unchecked" title="At least one number in this report could not be matched to the stats engine">
                        Some numbers unverified
                      </span>
                    )}{" "}
                    <ListenButton
                      language="en"
                      label="Listen"
                      text={[doc.report.headline, ...doc.report.changes.map((c, i) => `Change ${i + 1}: ${c.change}`)].join(". ")}
                    />
                  </p>
                  <h4>Working</h4>
                  <ul>{doc.report.working.map((w, i) => <li key={i}>{w}</li>)}</ul>
                  <h4>Not working</h4>
                  <ul>{doc.report.not_working.map((w, i) => <li key={i}>{w}</li>)}</ul>
                  <h4>Three changes to consider</h4>
                  <ol className="changes">
                    {doc.report.changes.map((c, i) => (
                      <li key={i}>
                        <strong>{c.change}</strong>
                        <span>{c.why}</span>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- Match story chart */
export function StoryChart({ history, events, overlays, meta, compact }: {
  history: HistoryPoint[];
  events: MatchEvent[];
  overlays: Overlay[];
  meta: Metadata | null;
  compact?: boolean;
}) {
  if (!meta || history.length < 2) {
    return <p className="muted">The match story chart draws itself as the game goes on.</p>;
  }
  const W = 640;
  const H = compact ? 130 : 220;
  const pad = { l: 34, r: 10, t: 14, b: 24 };
  const maxMin = Math.max(90, ...history.map((p) => p.minute));
  const x = (m: number) => pad.l + (m / maxMin) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / 100) * (H - pad.t - pad.b);
  const line = (key: "home" | "away" | "draw") =>
    history.map((p, i) => `${i ? "L" : "M"}${x(p.minute).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");
  const goals = events.filter((e) => e.type === "goal");
  const shifts = overlays.filter((o) => o.kind === "tactical_shift");
  return (
    <figure className="story-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Win probability across the match">
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="axis">
              {v}%
            </text>
          </g>
        ))}
        {[0, 45, 90].map((m) => (
          <text key={m} x={x(m)} y={H - 6} textAnchor="middle" className="axis">
            {m}'
          </text>
        ))}
        {shifts.map((o) => (
          <line key={o.overlay_id} x1={x(o.minute)} x2={x(o.minute)} y1={pad.t} y2={H - pad.b} className="shift-mark">
            <title>{`${o.minute}' ${o.headline}`}</title>
          </line>
        ))}
        <path d={line("draw")} className="wp-line draw" />
        <path d={line("home")} className="wp-line home" />
        <path d={line("away")} className="wp-line away" />
        {goals.map((g, i) => (
          <g key={i} transform={`translate(${x(g.minute)} ${pad.t + 2})`}>
            <circle r={5} className={g.side === "home" ? "goal-home" : "goal-away"} />
            <title>{`${g.minute}' goal: ${g.player ?? ""}`}</title>
          </g>
        ))}
      </svg>
      <figcaption>
        <span className="key home">{meta.home.short_name} win</span>
        <span className="key draw">Draw</span>
        <span className="key away">{meta.away.short_name} win</span>
        <span className="key goal">Goal</span>
        <span className="key shift">Tactical shift</span>
      </figcaption>
    </figure>
  );
}

export const languageName = (l: string) => LANG_NAMES[l] ?? l;
