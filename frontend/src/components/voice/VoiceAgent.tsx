// Voice assistant. Speech path, best available first:
//   1. Gemini: record a short clip (MediaRecorder) → /api/voice/audio → transcript + intent (server holds the key)
//   2. the browser's speech recognition (Chrome/Edge) → /api/voice
//   3. typing → /api/voice (always available)
// Answers come from ResQWork's live data; replies can open the matching screen, like the UI action would.
import React, { useEffect, useRef, useState } from 'react';
import { Mic, Square, Send, Volume2, VolumeX, X, Bell, Loader2 } from '../common/icons';
import { api, ApiError, errorMessage } from '../../api/client';
import type { VoiceReply } from '../../api/types';
import { canListen, canSpeak, listen, speak } from '../../lib/speech';
import { useToast } from '../../lib/toast';

interface Turn { who: 'you' | 'agent' | 'system'; text: string; meta?: string }

const SUGGESTIONS = ["Show today's schedule", 'Show me today\'s disruptions', 'What conflicts are unresolved?', 'What is the recommended repair?',
  'Which employees are affected?', 'Why was this employee reassigned?', 'What changed in the latest repair?', 'Show pending requests'];
const MAX_MS = 8000;

const canRecord = () => typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia;

export function VoiceAgent({ open, onClose, onAction, onNavigate }: {
  open: boolean; onClose: () => void; onAction: () => void; onNavigate: (n: { screen: string; proposal_id?: string }) => void;
}) {
  const toast = useToast();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<'idle' | 'recording' | 'listening' | 'thinking'>('idle');
  const [muted, setMuted] = useState(false);
  const [gemini, setGemini] = useState<{ on: boolean; model?: string | null } | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const stopListen = useRef<(() => void) | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [turns, mode]);
  useEffect(() => {
    if (!open) return;
    api.voiceStatus().then((s) => setGemini({ on: s.gemini, model: s.model })).catch(() => setGemini({ on: false }));
    if (turns.length === 0) alert();
    return () => { recRef.current?.state === 'recording' && recRef.current.stop(); stopListen.current?.(); };
  }, [open]);

  const say = (t: string, audio?: VoiceReply['audio']) => { if (!muted) speak(t, audio); };

  function handle(r: VoiceReply, typed: boolean) {
    if (!typed && r.transcript) setTurns((t) => [...t, { who: 'you', text: r.transcript! }]);
    setTurns((t) => [...t, { who: 'agent', text: r.text, meta: r.understood_by ? `understood by ${r.understood_by}` : undefined }]);
    say(r.text, r.audio);
    if (r.action) onAction();
    if (r.navigate) onNavigate(r.navigate);
  }

  async function alert() {
    setMode('thinking');
    try {
      const r = await api.voiceAlert();
      setTurns((t) => [...t, { who: 'agent', text: r.text }]);
      say(r.text, r.audio);
    } catch (e) { setTurns((t) => [...t, { who: 'system', text: errorMessage(e) }]); }
    finally { setMode('idle'); }
  }

  async function send(utterance: string) {
    if (!utterance.trim()) return;
    setTurns((t) => [...t, { who: 'you', text: utterance }]);
    setText('');
    setMode('thinking');
    try { handle(await api.voice(utterance), true); }
    catch (e) { setTurns((t) => [...t, { who: 'system', text: `That didn't work: ${errorMessage(e)}` }]); }
    finally { setMode('idle'); }
  }

  async function startRecording() {
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toast('Microphone permission was denied. You can type instead.', 'warning'); return; }
    const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => MediaRecorder.isTypeSupported?.(m)) ?? '';
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      window.clearTimeout(timer.current);
      const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
      setMode('thinking');
      try { handle(await api.voiceAudio(blob), false); }
      catch (e) {
        setTurns((t) => [...t, { who: 'system', text: `${errorMessage(e)} ${canListen() ? 'Switching to browser speech recognition.' : 'Please type the command.'}` }]);
        if (e instanceof ApiError && e.status === 503) setGemini({ on: false });
      } finally { setMode('idle'); }
    };
    recRef.current = rec;
    rec.start();
    setMode('recording');
    timer.current = window.setTimeout(() => rec.state === 'recording' && rec.stop(), MAX_MS);
  }

  function mic() {
    if (mode === 'recording') { recRef.current?.stop(); return; }
    if (mode === 'listening') { stopListen.current?.(); setMode('idle'); return; }
    if (gemini?.on && canRecord()) { startRecording(); return; }
    if (canListen()) {
      setMode('listening');
      stopListen.current = listen((t) => send(t), () => setMode((m) => (m === 'listening' ? 'idle' : m)));
      return;
    }
    toast('Voice input is not available in this browser. Type your question instead.', 'info');
  }

  if (!open) return null;
  const engine = gemini?.on ? `Gemini${gemini.model ? ` (${gemini.model})` : ''}` : canListen() ? 'browser speech recognition' : 'text only';
  return (
    <aside className="fixed right-4 bottom-4 z-40 w-[24rem] max-w-[calc(100vw-2rem)] bg-white border border-slate-200 rounded-xl shadow-2xl flex flex-col max-h-[75vh]"
           aria-label="Voice assistant">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${mode === 'recording' || mode === 'listening' ? 'bg-rose-500 animate-pulse' : 'bg-[var(--accent)]'}`} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">ResQWork assistant</p>
          <p className="text-[11px] text-slate-500 truncate">Voice: {engine}</p>
        </div>
        <button aria-label="Read latest alert" title="Read latest alert" onClick={alert} className="p-1 rounded hover:bg-slate-100 text-slate-500"><Bell className="w-4 h-4" /></button>
        <button aria-label={muted ? 'Turn speech on' : 'Turn speech off'} title={muted ? 'Speech off' : 'Speech on'}
                onClick={() => { setMuted(!muted); if (!muted && canSpeak()) window.speechSynthesis.cancel(); }}
                className="p-1 rounded hover:bg-slate-100 text-slate-500">{muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}</button>
        <button aria-label="Close assistant" onClick={onClose} className="p-1 rounded hover:bg-slate-100 text-slate-500"><X className="w-4 h-4" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2 text-xs" aria-live="polite">
        {turns.map((t, i) => (
          <div key={i} className={`max-w-[88%] rounded-lg px-3 py-2 ${t.who === 'you' ? 'ml-auto bg-[#0E1B2C] text-white' : t.who === 'system' ? 'bg-amber-50 text-amber-900 border border-amber-200' : 'bg-slate-100 text-slate-800'}`}>
            {t.text}{t.meta && <span className="block text-[10px] text-slate-500 mt-1">{t.meta}</span>}
          </div>
        ))}
        {mode === 'thinking' && <div className="bg-slate-100 text-slate-500 rounded-lg px-3 py-2 w-fit flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" />Working…</div>}
        {mode === 'recording' && <div className="text-rose-600 text-[11px]">Recording. Tap the square to send (stops after 8 s).</div>}
        {mode === 'listening' && <div className="text-rose-600 text-[11px]">Listening…</div>}
        <div ref={endRef} />
      </div>
      <div className="px-3 pb-2 flex flex-wrap gap-1">
        {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} disabled={mode !== 'idle'} className="text-[11px] px-2 py-0.5 rounded-full border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50">{s}</button>)}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="p-3 border-t border-slate-100 flex gap-1.5">
        <button type="button" onClick={mic} disabled={mode === 'thinking'}
                aria-label={mode === 'recording' ? 'Stop and send recording' : mode === 'listening' ? 'Stop listening' : 'Speak a command'}
                className={`w-9 h-9 shrink-0 rounded-full grid place-items-center border ${mode === 'recording' || mode === 'listening' ? 'bg-rose-600 border-rose-600 text-white' : 'border-slate-200 text-slate-700 hover:bg-slate-50'} disabled:opacity-50`}>
          {mode === 'recording' ? <Square className="w-3.5 h-3.5" /> : <Mic className="w-4 h-4" />}
        </button>
        <label htmlFor="voice-text" className="sr-only">Type a command</label>
        <input id="voice-text" className="input flex-1 min-w-0 h-9" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask or type a command" />
        <button type="submit" aria-label="Send" disabled={mode !== 'idle' || !text.trim()} className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-[#0E1B2C] text-white disabled:opacity-40"><Send className="w-3.5 h-3.5" /></button>
      </form>
    </aside>
  );
}
