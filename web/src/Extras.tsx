import { useState } from "react";
import type { CoachDoc, HistoryPoint, MatchEvent, Metadata, Overlay, Prefs, PunditReply } from "./types";
import { LANG_NAMES } from "./lib";

/* --------------------------------------------------------------- Ask the pundit */
const SUGGESTIONS = ["Why is this game so open?", "Who has been the best passer?", "Is the press working?"];

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
      setReplies((cur) => [{ question: text, ...d }, ...cur].slice(0, 4));
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
        {enabled && !replies.length && (
          <div className="chips">
            {SUGGESTIONS.map((s) => (
              <button type="button" key={s} className="chip" onClick={() => ask(s)} disabled={busy}>
                {s}
              </button>
            ))}
          </div>
        )}
      </form>
      {replies.map((r, i) => (
        <article key={i} className="reply">
          <p className="reply-q">{r.question}</p>
          <p>{r.answer}</p>
          <div className="insight-meta">
            {r.verified ? <span className="checked">Fact-checked</span> : <span className="unchecked">Unverified</span>}
            {r.minute != null && <span className="team-chip">at {r.minute}'</span>}
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
export function CoachView({ coach, meta, prefs, running }: {
  coach: Record<string, CoachDoc>;
  meta: Metadata | null;
  prefs: Prefs;
  running: boolean;
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
                <button className="chip" disabled={!!busy || !meta} onClick={() => generate(side)}>
                  {busy === side ? "Writing…" : doc ? "Refresh report" : running ? "Write report now" : "Write report"}
                </button>
              </header>
              {!doc?.report && <p className="muted">No report yet. It arrives at half-time.</p>}
              {doc?.report && (
                <>
                  <h3>{doc.report.headline}</h3>
                  <p className="muted">
                    At {doc.minute}' · {doc.verified ? "numbers fact-checked" : "unverified"}
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

/* --------------------------------------------------------------- Audio */
export async function playAudio(text: string, language: string): Promise<"azure" | "browser" | "none"> {
  try {
    const r = await fetch("/api/speech", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (r.status === 200) {
      const url = URL.createObjectURL(await r.blob());
      await new Audio(url).play();
      return "azure";
    }
  } catch {
    /* fall through to the browser voice */
  }
  if (!("speechSynthesis" in window)) return "none";
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = language === "hi" ? "hi-IN" : language === "es" ? "es-ES" : "en-GB";
  window.speechSynthesis.speak(u);
  return "browser";
}

export const languageName = (l: string) => LANG_NAMES[l] ?? l;
