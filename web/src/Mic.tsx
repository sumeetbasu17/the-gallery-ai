import { useEffect, useRef, useState } from "react";

/**
 * Voice input: dictate into any text box (Web Speech API, in the viewer's language).
 * Hidden when the browser can't do speech recognition (it works in Chrome and Edge).
 */
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: any) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: any) => void) | null;
  start: () => void;
  stop: () => void;
};

const LOCALES: Record<string, string> = {
  en: "en-GB",
  hi: "hi-IN",
  es: "es-ES",
};

function factory(): (new () => Recognition) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function MicButton({
  language,
  value,
  onText,
  onDone,
  label = "Speak",
}: {
  language: string;
  value: string;
  onText: (text: string) => void;
  /** Called with the final text when the speaker stops (e.g. to submit a question). */
  onDone?: (text: string) => void;
  label?: string;
}) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const rec = useRef<Recognition | null>(null);
  const wanted = useRef(false); // true until the viewer presses Stop
  const finalText = useRef("");
  const base = useRef("");
  const latest = useRef("");
  const Ctor = factory();
  useEffect(
    () => () => {
      wanted.current = false;
      rec.current?.stop();
    },
    [],
  );
  if (!Ctor) return null;

  // Keeps listening through pauses: the browser ends a session after silence, so we start a new one
  // (keeping what was already said) until the viewer presses Stop.
  const listen = () => {
    const r = new Ctor();
    r.lang = LOCALES[language] ?? "en-GB";
    r.interimResults = true;
    r.continuous = true;
    r.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal)
          finalText.current = `${finalText.current} ${t}`
            .replace(/\s+/g, " ")
            .trimStart();
        else interim += t;
      }
      latest.current =
        `${base.current}${finalText.current}${interim ? ` ${interim}` : ""}`.slice(
          0,
          400,
        );
      onText(latest.current);
    };
    r.onerror = (e: any) => {
      if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
        wanted.current = false;
        setError("Allow the microphone in your browser to speak.");
      }
    };
    r.onend = () => {
      if (wanted.current) {
        try {
          listen();
          return;
        } catch {
          /* fall through and stop */
        }
      }
      setListening(false);
      if (latest.current.trim() && latest.current.trim() !== value.trim())
        onDone?.(latest.current.trim());
    };
    rec.current = r;
    r.start();
  };

  const start = () => {
    setError("");
    base.current = value ? `${value.trim()} ` : "";
    latest.current = value;
    finalText.current = "";
    wanted.current = true;
    listen();
    setListening(true);
  };

  const stop = () => {
    wanted.current = false;
    rec.current?.stop();
  };

  return (
    <span className="mic-wrap">
      <button
        type="button"
        className={`mic ${listening ? "on" : ""}`}
        aria-pressed={listening}
        title={
          listening ? "Listening: press to stop" : `${label} (voice input)`
        }
        onClick={() => (listening ? stop() : start())}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
          <path
            d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z"
            fill="currentColor"
          />
        </svg>
        <span>{listening ? "Stop" : label}</span>
      </button>
      {error && <span className="field-error mic-error">{error}</span>}
    </span>
  );
}
