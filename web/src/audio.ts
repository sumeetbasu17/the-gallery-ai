/**
 * One voice for the whole app: Azure AI Speech when the server has it, the browser's voice otherwise.
 * Only one clip plays at a time; a new one stops the previous one.
 */

export type VoiceSource = "azure" | "browser" | "none";

let current: HTMLAudioElement | null = null;
let generation = 0;
/** Listeners hear whether anything is playing and which text it is, so each button knows if it's "its" audio. */
type Listener = (speaking: boolean, text: string | null) => void;
const listeners = new Set<Listener>();

function notify(speaking: boolean, text: string | null = null) {
  listeners.forEach((fn) => fn(speaking, speaking ? text : null));
}

export function onSpeaking(fn: Listener) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function halt() {
  generation += 1;
  if (current) {
    current.pause();
    current = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

export function stopSpeaking() {
  halt();
  notify(false);
}

/** Browsers cut long utterances off (Chrome stops after ~15 s), so speak sentence-sized chunks. */
function chunks(text: string, max = 180): string[] {
  const out: string[] = [];
  let cur = "";
  for (const part of text.split(/(?<=[.!?।])\s+/)) {
    if ((cur + " " + part).trim().length > max && cur) {
      out.push(cur.trim());
      cur = part;
    } else cur = `${cur} ${part}`;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

const LOCALES: Record<string, string> = { en: "en-GB", hi: "hi-IN", es: "es-ES" };

/** Speak `text`; resolves with how it was voiced once playback has finished (or was stopped). */
export async function say(text: string, language: string, onStart?: (how: VoiceSource) => void): Promise<VoiceSource> {
  halt(); // stop whatever was playing, without telling listeners "silence" (we're about to speak)
  const mine = generation;
  notify(true, text);
  try {
    const r = await fetch("/api/speech", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (mine !== generation) return "none";
    if (r.status === 200) {
      const url = URL.createObjectURL(await r.blob());
      if (mine !== generation) return "none";
      const audio = new Audio(url);
      current = audio;
      onStart?.("azure");
      await new Promise<void>((resolve) => {
        audio.onended = audio.onerror = audio.onpause = () => resolve();
        audio.play().catch(() => resolve());
      });
      URL.revokeObjectURL(url);
      if (mine === generation) notify(false);
      return "azure";
    }
  } catch {
    /* fall through to the browser voice */
  }
  if (mine !== generation) return "none";
  if (!("speechSynthesis" in window)) {
    notify(false);
    return "none";
  }
  const lang = LOCALES[language] ?? "en-GB";
  const voices = window.speechSynthesis.getVoices();
  const voice =
    voices.find((v) => v.lang.replace("_", "-") === lang) ?? voices.find((v) => v.lang.startsWith(lang.slice(0, 2)));
  onStart?.("browser");
  for (const piece of chunks(text)) {
    if (mine !== generation) break;
    const u = new SpeechSynthesisUtterance(piece);
    u.lang = lang;
    u.rate = 1.02;
    if (voice) u.voice = voice;
    await new Promise<void>((resolve) => {
      u.onend = u.onerror = () => resolve();
      window.speechSynthesis.speak(u);
    });
  }
  if (mine === generation) notify(false);
  return "browser";
}
