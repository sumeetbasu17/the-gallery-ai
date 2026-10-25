/**
 * One voice for the whole app: Azure AI Speech when the server has it, the browser's voice otherwise.
 * Only one clip plays at a time; a new one stops the previous one.
 */

export type VoiceSource = "azure" | "browser" | "none";

let current: HTMLAudioElement | null = null;
let generation = 0;
const listeners = new Set<(speaking: boolean) => void>();

function notify(speaking: boolean) {
  listeners.forEach((fn) => fn(speaking));
}

export function onSpeaking(fn: (speaking: boolean) => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function stopSpeaking() {
  generation += 1;
  if (current) {
    current.pause();
    current = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  notify(false);
}

const LOCALES: Record<string, string> = { en: "en-GB", hi: "hi-IN", es: "es-ES" };

/** Speak `text`; resolves with how it was voiced once playback has finished (or was stopped). */
export async function say(text: string, language: string, onStart?: (how: VoiceSource) => void): Promise<VoiceSource> {
  stopSpeaking();
  const mine = generation;
  notify(true);
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
  const u = new SpeechSynthesisUtterance(text);
  u.lang = LOCALES[language] ?? "en-GB";
  u.rate = 1.02;
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.replace("_", "-").startsWith(u.lang.slice(0, 2)));
  if (voice) u.voice = voice;
  onStart?.("browser");
  await new Promise<void>((resolve) => {
    u.onend = u.onerror = () => resolve();
    window.speechSynthesis.speak(u);
  });
  if (mine === generation) notify(false);
  return "browser";
}
