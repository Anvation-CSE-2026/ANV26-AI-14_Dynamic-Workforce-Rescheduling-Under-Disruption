// Browser speech (Web Speech API): zero-key voice for the alert agent; text is always shown as fallback.

export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window;
export const canListen = () =>
  typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

export function speak(text: string, audio?: { mime: string; base64: string } | null) {
  if (audio?.base64) {
    new Audio(`data:${audio.mime};base64,${audio.base64}`).play().catch(() => speak(text));
    return;
  }
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.02;
  window.speechSynthesis.speak(u);
}

/** The Web Speech recognition API isn't in TypeScript's DOM library yet; this is the subset we use. */
interface SpeechRecognitionLike {
  lang: string; interimResults: boolean; maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null; start(): void; stop(): void;
}
type SpeechWindow = Window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };

export function listen(onText: (t: string) => void, onEnd: () => void): (() => void) | null {
  const w = window as SpeechWindow;
  const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!SR) return null;
  const rec = new SR();
  rec.lang = 'en-IN';
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (e) => onText(e.results[0][0].transcript);
  rec.onend = onEnd;
  rec.onerror = onEnd;
  rec.start();
  return () => rec.stop();
}
