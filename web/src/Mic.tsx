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
  const base = useRef("");
  const latest = useRef("");
  const Ctor = factory();
  useEffect(() => () => rec.current?.stop(), []);
  if (!Ctor) return null;

  const start = () => {
    setError("");
    const r = new Ctor();
    r.lang = LOCALES[language] ?? "en-GB";
    r.interimResults = true;
    r.continuous = false;
    base.current = value ? `${value.trim()} ` : "";
    latest.current = value;
    r.onresult = (e: any) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++)
        text += e.results[i][0].transcript;
      latest.current = (base.current + text).slice(0, 400);
      onText(latest.current);
    };
    r.onerror = (e: any) =>
      setError(
        e?.error === "not-allowed"
          ? "Allow the microphone in your browser to speak."
          : "Didn't catch that. Try again.",
      );
    r.onend = () => {
      setListening(false);
      if (latest.current.trim() && latest.current !== value)
        onDone?.(latest.current);
    };
    rec.current = r;
    r.start();
    setListening(true);
  };

  return (
    <span className="mic-wrap">
      <button
        type="button"
        className={`mic ${listening ? "on" : ""}`}
        aria-pressed={listening}
        title={listening ? "Stop listening" : `${label} (voice input)`}
        onClick={() => (listening ? rec.current?.stop() : start())}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
          <path
            d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z"
            fill="currentColor"
          />
        </svg>
        <span>{listening ? "Listening…" : label}</span>
      </button>
      {error && <span className="field-error mic-error">{error}</span>}
    </span>
  );
}
