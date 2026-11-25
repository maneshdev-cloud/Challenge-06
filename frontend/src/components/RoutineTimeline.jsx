import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  FileText,
  MessageCircle,
  RefreshCw,
  Shield,
  Sparkles,
  Square,
  Users,
  Volume2
} from "lucide-react";
import { copyToClipboard, formatHourAmPm } from "../utils/formatters";
import {
  canUseSpeechSynthesis,
  formatTextForSpeech,
  pickBestVoice
} from "../utils/pwaAndPermissions";
import FormattedText from "./FormattedText";

function friendlyBadge(badge) {
  if (badge.startsWith("FIXED")) {
    return { text: "Fixed • Protected", cls: "bg-amber-100 text-amber-900" };
  }
  if (badge.includes("INDOOR")) {
    return { text: "Moved Indoors", cls: "bg-sky-100 text-sky-900" };
  }
  if (badge.startsWith("WHAT-IF")) {
    return { text: "What-If Preview", cls: "bg-indigo-100 text-indigo-900" };
  }
  if (badge.includes("SHIFTED")) {
    return { text: "Shifted to Cleaner Hour", cls: "bg-emerald-100 text-emerald-900" };
  }
  return { text: "Kept on Track", cls: "bg-slate-200 text-slate-800" };
}

function buildShareSummary(bundle, narrative) {
  if (!bundle) return "";
  const { air_snapshot: air, sanctuary_plan: sp, breathe_less: bl, emit_less: el } = bundle;
  const loc =
    air.area_name && air.area_name !== air.city_name
      ? `${air.area_name}, ${air.city_name}`
      : air.city_name;
  const co2Str = el.co2_saved_g >= 1000 ? `${el.co2_saved_kg} kg` : `${el.co2_saved_g} g`;
  const cleanBrief = (narrative || "").replace(/\*\*/g, "").trim();

  return [
    `PRANA-AI Daily Plan — ${loc}`,
    `Today's Air: PM2.5 ${air.current_pm25} ug/m3 | Est. India AQI ${air.current_naqi} (${air.current_category})`,
    `Best Time Outside: ${air.golden_window.window_label}`,
    `Safest Indoor Room: ${sp.sanctuary_room}`,
    "",
    cleanBrief,
    "",
    `Modeled Impact: ${bl.reduction_pct}% less pollution breathed (-${bl.dose_avoided_ug} ug PM2.5) | ${co2Str} CO2 saved`
  ].join("\n");
}

export default function RoutineTimeline({
  bundle,
  routinePlan,
  members,
  selectedMember,
  onSelectMember,
  narrative,
  narrativeSource,
  validatorPassed,
  onExplainWithGemini,
  explaining,
  onOpenCleanAirNote
}) {
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsHint, setTtsHint] = useState(null);
  const ttsSupported = canUseSpeechSynthesis();

  useEffect(() => {
    if (ttsSupported) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
    return () => {
      if (canUseSpeechSynthesis()) {
        window.speechSynthesis.cancel();
      }
    };
  }, [narrative, bundle?.language, ttsSupported]);

  function handleToggleListen() {
    if (!ttsSupported || !narrative) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    try {
      setTtsHint(null);
      window.speechSynthesis.cancel();
      const spoken = formatTextForSpeech(narrative);
      const utterance = new SpeechSynthesisUtterance(spoken);
      const { voice, langTag } = pickBestVoice(bundle?.language || "en");
      if (voice) utterance.voice = voice;
      utterance.lang = langTag;
      utterance.rate = 0.98;
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => {
        setSpeaking(false);
        setTtsHint("Voice playback unavailable on this device.");
      };
      setSpeaking(true);
      window.speechSynthesis.speak(utterance);
    } catch {
      setSpeaking(false);
      setTtsHint("Could not start voice playback in this browser.");
    }
  }

  const memberNames = Array.from(
    new Set(
      [...(members || []).map((m) => m.name), ...(routinePlan || []).map((r) => r.member_name)].filter(
        Boolean
      )
    )
  );

  const filtered = (routinePlan || []).filter(
    (item) => selectedMember === "ALL" || item.member_name === selectedMember
  );
  const sorted = [...filtered].sort((a, b) => a.recommended_hour - b.recommended_hour);
  const memberSavedUg =
    Math.round(sorted.reduce((sum, item) => sum + (item.dose_avoided_ug || 0), 0) * 10) / 10;

  const shareText = buildShareSummary(bundle, narrative);
  const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(shareText)}`;

  async function handleCopyPlan() {
    if (!shareText) return;
    const ok = await copyToClipboard(shareText);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  }

  return (
    <section className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Your Daily Schedule</h2>
          <p className="mt-0.5 text-xs text-slate-600">
            Flexible errands move to cleaner hours; fixed work and school stay protected.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleCopyPlan}
            className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-900 ring-1 ring-emerald-200 transition hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
            ) : (
              <Copy className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
            )}
            <span>{copied ? "Copied for WhatsApp!" : "Copy / Share Today's Plan"}</span>
          </button>

          <a
            href={whatsappUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <MessageCircle className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
            <span>WhatsApp</span>
          </a>

          {onOpenCleanAirNote && (
            <button
              type="button"
              onClick={onOpenCleanAirNote}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600 ${
                (bundle?.air_snapshot?.current_naqi || 0) > 150
                  ? "bg-amber-100 text-amber-950 ring-1 ring-amber-300 hover:bg-amber-200"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              <FileText className="h-3.5 w-3.5 text-amber-700" aria-hidden="true" />
              <span>School / Office Note</span>
            </button>
          )}

          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold ${
              narrativeSource === "gemini"
                ? "bg-violet-50 text-violet-900 ring-1 ring-violet-200"
                : "bg-slate-100 text-slate-700"
            }`}
          >
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            <span>
              {narrativeSource === "gemini" ? "AI Summary" : "Deterministic Fallback Engine"}
            </span>
            {validatorPassed && (
              <CheckCircle2 className="h-3 w-3 text-emerald-600" aria-hidden="true" />
            )}
          </span>
        </div>
      </div>

      {/* Member Filter Pill Bar */}
      {memberNames.length > 0 && (
        <div
          role="group"
          aria-label="Filter schedule by family member"
          className="mt-4 flex flex-wrap items-center gap-2 rounded-2xl bg-slate-50 p-2 ring-1 ring-slate-200/70"
        >
          <span className="inline-flex items-center gap-1 pl-2 text-[11px] font-bold uppercase tracking-wide text-slate-600">
            <Users className="h-3.5 w-3.5" aria-hidden="true" /> Filter:
          </span>
          <button
            type="button"
            aria-pressed={selectedMember === "ALL"}
            onClick={() => onSelectMember("ALL")}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
              selectedMember === "ALL"
                ? "bg-slate-900 text-white shadow-sm"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-100"
            }`}
          >
            All Members
          </button>
          {memberNames.map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={selectedMember === name}
              onClick={() => onSelectMember(name)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                selectedMember === name
                  ? "bg-teal-700 text-white shadow-sm"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-teal-50"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {selectedMember !== "ALL" && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-gradient-to-r from-teal-50 to-emerald-50/70 px-4 py-2.5 text-xs ring-1 ring-teal-200/80">
          <span className="font-bold text-teal-950">
            Focused Plan for {selectedMember} ({sorted.length}{" "}
            {sorted.length === 1 ? "task" : "tasks"})
          </span>
          <span className="font-mono font-bold text-teal-800">
            {memberSavedUg >= 0
              ? `-${memberSavedUg} ug PM2.5 avoided`
              : `+${Math.abs(memberSavedUg)} ug PM2.5`}
          </span>
        </div>
      )}

      {/* Scannable Daily Brief */}
      {narrative && (
        <div className="mt-4 rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900 to-teal-950 p-4 text-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-teal-300">
              Today&apos;s Guidance
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {ttsSupported && (
                <button
                  type="button"
                  onClick={handleToggleListen}
                  aria-label={speaking ? "Stop voice brief" : "Listen to daily brief"}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 ${
                    speaking
                      ? "bg-rose-600 text-white hover:bg-rose-700"
                      : "bg-teal-600 text-white hover:bg-teal-500"
                  }`}
                >
                  {speaking ? (
                    <Square className="h-3 w-3 fill-current" aria-hidden="true" />
                  ) : (
                    <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  <span>{speaking ? "Stop" : "Listen"}</span>
                </button>
              )}
              {onExplainWithGemini && (
                <button
                  type="button"
                  disabled={explaining}
                  onClick={onExplainWithGemini}
                  className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-[11px] font-semibold text-white transition hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-60"
                >
                  <RefreshCw
                    className={`h-3 w-3 ${explaining ? "animate-spin" : ""}`}
                    aria-hidden="true"
                  />
                  {explaining ? "Refreshing..." : "Refresh AI Brief"}
                </button>
              )}
            </div>
          </div>
          {ttsHint && (
            <p role="status" aria-live="polite" className="mt-1.5 text-[11px] font-medium text-amber-300">
              {ttsHint}
            </p>
          )}
          <div className="mt-2.5 text-sm text-slate-100">
            <FormattedText text={narrative} dark />
          </div>
        </div>
      )}

      {/* Chronological Activity Cards */}
      <div className="mt-5 space-y-3">
        {sorted.length === 0 ? (
          <div className="rounded-2xl bg-slate-50 p-5 text-center text-xs text-slate-600">
            No scheduled tasks assigned to {selectedMember} yet. Click &quot;Edit Household&quot; to add one.
          </div>
        ) : (
          sorted.map((item) => {
            const b = friendlyBadge(item.badge);
            return (
              <div
                key={item.id}
                className="rounded-2xl bg-gradient-to-br from-slate-50/90 to-white p-4 ring-1 ring-slate-200/80 transition-all duration-200 hover:shadow-md"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${b.cls}`}
                      >
                        {b.text}
                      </span>
                      <span className="text-xs font-semibold text-slate-700">{item.member_name}</span>
                      <span className="text-xs text-slate-600">{item.duration_min} min</span>
                    </div>
                    <h3 className="mt-1.5 text-sm font-bold text-slate-900">{item.name}</h3>
                  </div>

                  <div className="text-right font-mono text-xs tabular-nums">
                    <div className="flex items-center justify-end gap-1.5 font-bold text-slate-800">
                      <Clock className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
                      {item.original_hour !== item.recommended_hour ? (
                        <>
                          <span className="text-slate-600 line-through">
                            {formatHourAmPm(item.original_hour)}
                          </span>
                          <ArrowRight className="h-3 w-3 text-emerald-700" aria-hidden="true" />
                          <span className="text-emerald-800">
                            {formatHourAmPm(item.recommended_hour)}
                          </span>
                        </>
                      ) : (
                        <span>{formatHourAmPm(item.recommended_hour)}</span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-slate-600">
                      {item.recommended_pm25} ug/m3 • Est. AQI {item.recommended_naqi}
                    </p>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 font-semibold text-slate-700 ring-1 ring-slate-200/80">
                    <Shield className="h-3 w-3 text-teal-700" aria-hidden="true" />
                    Mask: {item.recommended_mask.toUpperCase()}
                  </span>
                  <span
                    className={`whitespace-nowrap rounded-full px-2.5 py-1 font-mono text-[11px] font-bold tabular-nums ${
                      item.dose_avoided_ug >= 0
                        ? "bg-emerald-100 text-emerald-900"
                        : "bg-rose-100 text-rose-900"
                    }`}
                  >
                    {item.dose_avoided_ug >= 0
                      ? `-${item.dose_avoided_ug} ug PM2.5 avoided`
                      : `+${Math.abs(item.dose_avoided_ug)} ug higher dose`}
                  </span>
                </div>

                <ul className="mt-3 space-y-1.5">
                  {item.mitigation_steps.map((step, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-xs text-slate-700">
                      <CheckCircle2
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal-700"
                        aria-hidden="true"
                      />
                      <span>{step}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
