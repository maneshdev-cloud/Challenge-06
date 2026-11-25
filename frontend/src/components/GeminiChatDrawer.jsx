import React, { useEffect, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Send, ShieldAlert, Sparkles } from "lucide-react";
import { getSpeechRecognitionCtor, isSecureOriginForDevices, SPEECH_LANG_MAP } from "../utils/pwaAndPermissions";
import FormattedText from "./FormattedText";

const SAMPLE_QUESTIONS = [
  "Can my dad still walk at 7 AM?",
  "When should we open bedroom or kitchen windows?",
  "Do indoor houseplants clean PM2.5?",
  "My son is wheezing badly"
];

export default function GeminiChatDrawer({
  evidenceBundle,
  language,
  messages,
  onAddMessage,
  onSendMessage,
  onEmergencyTriggered,
  onOpenPermissions
}) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [micStatus, setMicStatus] = useState(null);
  const recognitionRef = useRef(null);
  const speechSupported = Boolean(getSpeechRecognitionCtor());

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        // ignore cleanup error
      }
    };
  }, []);

  function toggleVoiceInput() {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    if (listening) {
      try {
        recognitionRef.current?.stop();
      } catch {
        // ignore
      }
      setListening(false);
      return;
    }

    if (!isSecureOriginForDevices()) {
      setMicStatus({
        blocked: true,
        text: "Voice input requires HTTPS on mobile browsers. Type your question or open Permissions."
      });
      return;
    }

    try {
      setMicStatus(null);
      const rec = new Ctor();
      rec.lang = SPEECH_LANG_MAP[language] || "en-IN";
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.continuous = false;

      rec.onresult = (event) => {
        let transcript = "";
        for (let i = 0; i < event.results.length; i += 1) {
          transcript += event.results[i][0].transcript;
        }
        if (transcript.trim()) {
          setInput(transcript.trim());
        }
      };

      rec.onerror = (event) => {
        setListening(false);
        const code = event?.error || "unknown";
        if (code === "not-allowed" || code === "service-not-allowed") {
          setMicStatus({
            blocked: true,
            text: "Microphone permission blocked on your phone. Tap Manage Permissions to allow."
          });
        } else if (code === "no-speech") {
          setMicStatus({ blocked: false, text: "Did not catch speech—tap Mic and speak clearly." });
        } else if (code === "audio-capture") {
          setMicStatus({ blocked: true, text: "No active microphone detected on this device." });
        } else {
          setMicStatus({ blocked: false, text: "Voice input stopped; type or tap Mic to retry." });
        }
      };

      rec.onend = () => {
        setListening(false);
      };

      recognitionRef.current = rec;
      setListening(true);
      rec.start();
    } catch {
      setListening(false);
      setMicStatus({ blocked: false, text: "Could not start voice recognition on this browser." });
    }
  }

  async function handleSubmit(textToSend) {
    const clean = (textToSend ?? input).trim();
    if (!clean || !evidenceBundle || sending) return;

    onAddMessage({ role: "user", text: clean });
    if (!textToSend) setInput("");
    setSending(true);

    try {
      const res = await onSendMessage(clean, evidenceBundle, language);
      onAddMessage({
        role: "assistant",
        text: res.reply,
        source: res.source,
        emergency: res.emergency_alert
      });
      if (res.emergency_alert && res.emergency_message) {
        onEmergencyTriggered(res.emergency_message);
      }
    } catch (err) {
      onAddMessage({
        role: "assistant",
        text: `Unable to reach PRANA-AI chat right now (${err.message}).`,
        source: "error"
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="rounded-3xl bg-white shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70">
      <div className="flex items-center gap-3 border-b border-slate-100 bg-gradient-to-r from-violet-50/70 via-white to-teal-50/50 px-5 py-4 rounded-t-3xl">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
          <Sparkles className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-base font-extrabold text-slate-900">Ask PRANA-AI</h2>
          <p className="text-xs text-slate-500">
            Answers grounded in Today&apos;s Live Data with automatic medical triage safety check
          </p>
        </div>
      </div>

      {/* Quick Prompt Chips */}
      <div className="flex flex-wrap gap-2 border-b border-slate-100 bg-slate-50/60 px-5 py-3">
        {SAMPLE_QUESTIONS.map((q) => {
          const isEmergencyPrompt = q.toLowerCase().includes("wheezing");
          return (
            <button
              key={q}
              type="button"
              disabled={sending}
              onClick={() => handleSubmit(q)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                isEmergencyPrompt
                  ? "bg-rose-50 text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-teal-50 hover:text-teal-800"
              }`}
            >
              {isEmergencyPrompt && <ShieldAlert className="h-3.5 w-3.5 text-rose-600" />}
              {q}
            </button>
          );
        })}
      </div>

      {/* Message History */}
      <div className="max-h-80 space-y-3 overflow-y-auto p-5">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-xs leading-relaxed sm:text-sm ${
                m.role === "user"
                  ? "bg-slate-900 text-white"
                  : m.emergency
                  ? "border-2 border-red-500 bg-red-50 font-semibold text-red-950"
                  : "bg-slate-100 text-slate-800"
              }`}
            >
              <FormattedText text={m.text} dark={m.role === "user"} />
              {m.source && m.role === "assistant" && m.source !== "system" && (
                <span className="mt-1.5 block text-[10px] font-semibold uppercase tracking-wide opacity-65">
                  {m.source === "deterministic_template"
                    ? "Offline Smart Engine"
                    : m.source === "gemini"
                    ? "Source: Gemini AI"
                    : "Emergency Triage"}
                </span>
              )}
            </div>
          </div>
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="inline-flex items-center gap-2 rounded-2xl bg-slate-100 px-4 py-2.5 text-xs font-semibold text-slate-600">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-700" />
              <span>Checking Today&apos;s Live Data...</span>
            </div>
          </div>
        )}
      </div>

      {/* Mic status / phone permission guidance */}
      {micStatus && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-amber-100 bg-amber-50/90 px-4 py-2 text-xs text-amber-950">
          <span>{micStatus.text}</span>
          {micStatus.blocked && onOpenPermissions && (
            <button
              type="button"
              onClick={onOpenPermissions}
              className="rounded-full bg-amber-900 px-3 py-1 text-[11px] font-bold text-white hover:bg-amber-800"
            >
              Manage Permissions
            </button>
          )}
        </div>
      )}

      {/* Input Form */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit();
        }}
        className="flex items-center gap-2 border-t border-slate-100 p-4"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={listening ? "Listening..." : "Ask in EN, Hinglish, HI, MR, KN, BN, TA, or TE..."}
          className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-900 placeholder:text-slate-400 focus:border-teal-600 focus:bg-white focus:outline-none sm:text-sm"
        />
        {speechSupported && (
          <button
            type="button"
            disabled={sending}
            onClick={toggleVoiceInput}
            aria-label={listening ? "Stop voice recording" : "Ask by voice"}
            title={listening ? "Stop recording" : "Speak your question"}
            className={`inline-flex shrink-0 items-center justify-center rounded-2xl p-2.5 transition ${
              listening
                ? "animate-pulse bg-rose-600 text-white shadow-sm hover:bg-rose-700"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
        )}
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-2xl bg-slate-900 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-slate-800 disabled:opacity-40"
        >
          {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          <span>{sending ? "Sending" : "Send"}</span>
        </button>
      </form>
    </section>
  );
}
