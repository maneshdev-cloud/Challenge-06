import { useMemo, useState } from "react";
import { Building2, CalendarPlus, Check, Copy, FileText, GraduationCap, Mail, MessageCircle, Users, X } from "lucide-react";
import { computeCommunityImpact, generateCleanWindowIcs } from "../utils/communityAndCalendar";
import { copyToClipboard } from "../utils/formatters";
import Modal from "./Modal";

function buildCleanAirNoteText(bundle, mode, senderNote, rwaHomes = 50) {
  if (!bundle?.air_snapshot) return "";
  const air = bundle.air_snapshot;
  const gw = air.golden_window;
  const loc =
    air.area_name && air.area_name.toLowerCase() !== air.city_name.toLowerCase()
      ? `${air.area_name}, ${air.city_name}`
      : air.city_name;
  const extra = senderNote?.trim() ? `\n\nFamily / Society Note: ${senderNote.trim()}` : "";

  if (mode === "school") {
    return (
      `Subject: Request for Indoor Assembly / PE Precaution Today (${loc})\n\n` +
      `Dear Principal / Class Teacher,\n\n` +
      `Live air quality in ${loc} today is ${air.current_category} ` +
      `(Est. India NAQI ${air.current_naqi}, PM2.5 ${air.current_pm25} ug/m3), ` +
      `with morning smog peaking around ${gw.morning_peak_pm25} ug/m3.\n\n` +
      `May we request holding morning assembly and PE / sports activities indoors today, ` +
      `or shifting brief light outdoor breaks closer to the cleaner midday window (${gw.window_label}, ~${gw.mean_pm25} ug/m3)? ` +
      `We have sent a fitted N95 mask for commute transitions.` +
      `${extra}\n\nThank you for caring for our children's health.\nSent via PRANA-AI`
    );
  }

  if (mode === "community") {
    const rwa = computeCommunityImpact(bundle, rwaHomes);
    return (
      `Subject: ${loc} Society / RWA Clean-Air Advisory (${gw.window_label})\n\n` +
      `Dear Neighbors (${rwa.householdsCount} Participating Homes),\n\n` +
      `Today's air in ${loc} is ${air.current_category} (Est. India NAQI ${air.current_naqi}, PM2.5 ${air.current_pm25} ug/m3).\n` +
      `- Cleanest outdoor / ventilation slot: ${gw.window_label} (~${gw.mean_pm25} ug/m3)\n` +
      `- Modeled scenario estimate if ${rwa.householdsCount} homes mirror today's shifts (not measured neighborhood data): ~${rwa.dailyCo2SavedKg} kg CO2e saved today (~${rwa.monthlyCo2SavedKg} kg/30 days) and ~${rwa.dailyDoseSavedMg} mg PM2.5 lung exposure avoided.\n` +
      `- Society checklist: Wet-mop common corridors (no dry brooms), avoid leaf/trash burning, and keep gate security N95-equipped.` +
      `${extra}\n\nTogether for cleaner neighborhood air — Sent via PRANA-AI`
    );
  }

  return (
    `Subject: Smog-Safe Shift & Mask Precaution Request (${loc})\n\n` +
    `Hello Team / Manager,\n\n` +
    `Today's live air quality in ${loc} stands at Est. India NAQI ${air.current_naqi} ` +
    `(${air.current_category}, PM2.5 ${air.current_pm25} ug/m3), reaching ${gw.morning_peak_pm25} ug/m3 during early peak hours.\n\n` +
    `Could we shift non-urgent outdoor tasks toward the cleaner window (${gw.window_label}, ~${gw.mean_pm25} ug/m3) ` +
    `or allow brief indoor breaks away from roadside traffic plus fitted N95 masks during outdoor shifts?` +
    `${extra}\n\nAppreciate the support!\nSent via PRANA-AI`
  );
}

export default function CleanAirNoteModal({ open, onClose, bundle }) {
  const [mode, setMode] = useState("school");
  const [rwaHomes, setRwaHomes] = useState(50);
  const [senderNote, setSenderNote] = useState("");
  const [copied, setCopied] = useState(false);

  const noteText = useMemo(
    () => buildCleanAirNoteText(bundle, mode, senderNote, rwaHomes),
    [bundle, mode, senderNote, rwaHomes]
  );
  const rwaSummary = useMemo(
    () => computeCommunityImpact(bundle, rwaHomes),
    [bundle, rwaHomes]
  );

  if (!bundle) return null;

  const subjectLine =
    mode === "school"
      ? `Indoor Assembly / PE Request Today — ${bundle.air_snapshot.city_name} NAQI ${bundle.air_snapshot.current_naqi}`
      : mode === "community"
        ? `Society Clean-Air Bulletin (${rwaSummary.householdsCount} Homes) — ${bundle.air_snapshot.city_name}`
        : `Smog Precaution / Shift Timing Note — ${bundle.air_snapshot.city_name} NAQI ${bundle.air_snapshot.current_naqi}`;

  const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(noteText)}`;
  const mailtoUrl = `mailto:?subject=${encodeURIComponent(subjectLine)}&body=${encodeURIComponent(
    noteText
  )}`;

  async function handleCopy() {
    const ok = await copyToClipboard(noteText);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2400);
    }
  }

  function handleDownloadIcs() {
    const icsText = generateCleanWindowIcs(bundle);
    if (!icsText) return;
    const blob = new Blob([icsText], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `prana-clean-window-${bundle.air_snapshot.city || "india"}.ics`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      labelledBy="clean-air-note-modal-title"
      maxWidthClass="max-w-lg"
      panelClassName="max-h-[90vh] overflow-y-auto rounded-3xl bg-white p-5 shadow-2xl ring-1 ring-slate-200 sm:p-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-800">
            <FileText className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h2 id="clean-air-note-modal-title" className="text-base font-extrabold text-slate-900">
              School / Office Clean-Air Note
            </h2>
            <p className="text-xs text-slate-600">
              Polite ready-to-send request citing live PM2.5, Est. India NAQI &amp; peak smog window
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close note generator"
          className="rounded-xl p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div role="group" aria-label="Recipient type" className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <button
          type="button"
          aria-pressed={mode === "school"}
          onClick={() => setMode("school")}
          className={`flex items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${mode === "school"
            ? "bg-slate-900 text-white shadow-sm"
            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
        >
          <GraduationCap className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>School (Indoor PE)</span>
        </button>

        <button
          type="button"
          aria-pressed={mode === "workplace"}
          onClick={() => setMode("workplace")}
          className={`flex items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${mode === "workplace"
            ? "bg-slate-900 text-white shadow-sm"
            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
        >
          <Building2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>Workplace / Shift</span>
        </button>

        <button
          type="button"
          aria-pressed={mode === "community"}
          onClick={() => setMode("community")}
          className={`flex items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${mode === "community"
            ? "bg-slate-900 text-white shadow-sm"
            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
        >
          <Users className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>RWA / Society</span>
        </button>
      </div>

      {mode === "community" && (
        <div className="mt-3 space-y-1.5 rounded-2xl bg-teal-50 px-3.5 py-2.5 text-xs ring-1 ring-teal-200">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <label htmlFor="rwa-homes-count" className="font-bold text-teal-950">
                Participating Homes:
              </label>
              <input
                id="rwa-homes-count"
                type="number"
                min={1}
                max={5000}
                value={rwaHomes}
                onChange={(e) => setRwaHomes(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))}
                className="w-20 rounded-lg border border-teal-300 bg-white px-2 py-1 font-mono text-xs font-bold text-slate-900"
              />
            </div>
            <span className="font-semibold text-teal-900">
              ~{rwaSummary.monthlyCo2SavedKg} kg CO2e/mo • ~{rwaSummary.dailyDoseSavedMg} mg PM2.5 avoided/day
            </span>
          </div>
          <p className="text-[11px] text-teal-900">
            Scenario estimate assuming {rwaSummary.householdsCount} similar households adopt this plan (not measured neighborhood telemetry).
          </p>
        </div>
      )}

      <div className="mt-3">
        <label
          htmlFor="clean-air-sender-note"
          className="block text-[11px] font-bold uppercase tracking-wide text-slate-600"
        >
          Optional Child / Team Name or Asthma Note
        </label>
        <input
          id="clean-air-sender-note"
          type="text"
          value={senderNote}
          onChange={(e) => setSenderNote(e.target.value)}
          placeholder="e.g., Aarav (Class 4B) carries a spare rescue inhaler"
          className="mt-1.5 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-900 placeholder:text-slate-500 focus:border-teal-600 focus:bg-white focus:outline-none"
        />
      </div>

      <pre className="mt-3 whitespace-pre-wrap rounded-2xl bg-slate-50 p-3.5 font-sans text-xs leading-relaxed text-slate-800 ring-1 ring-slate-200">
        {noteText}
      </pre>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2 text-xs font-bold text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" />
          ) : (
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          <span>{copied ? "Copied Note!" : "Copy Note"}</span>
        </button>

        <a
          href={whatsappUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3.5 py-2 text-xs font-bold text-emerald-900 ring-1 ring-emerald-200 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
        >
          <MessageCircle className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
          <span>WhatsApp</span>
        </a>

        <a
          href={mailtoUrl}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <Mail className="h-3.5 w-3.5 text-slate-600" aria-hidden="true" />
          <span>Open Email Draft</span>
        </a>

        <button
          type="button"
          onClick={handleDownloadIcs}
          className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3.5 py-2 text-xs font-bold text-teal-900 ring-1 ring-teal-200 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <CalendarPlus className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          <span>Calendar (.ics)</span>
        </button>
      </div>
    </Modal>
  );
}
