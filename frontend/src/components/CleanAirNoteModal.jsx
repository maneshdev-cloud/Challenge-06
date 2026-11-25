import { useMemo, useState } from "react";
import { Building2, Check, Copy, FileText, GraduationCap, Mail, MessageCircle, X } from "lucide-react";
import { copyToClipboard } from "../utils/clipboard";
import Modal from "./Modal";

function buildCleanAirNoteText(bundle, mode, senderNote) {
  if (!bundle?.air_snapshot) return "";
  const air = bundle.air_snapshot;
  const gw = air.golden_window;
  const loc =
    air.area_name && air.area_name.toLowerCase() !== air.city_name.toLowerCase()
      ? `${air.area_name}, ${air.city_name}`
      : air.city_name;
  const extra = senderNote?.trim() ? `\n\nFamily / Employee Note: ${senderNote.trim()}` : "";

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
  const [senderNote, setSenderNote] = useState("");
  const [copied, setCopied] = useState(false);

  const noteText = useMemo(
    () => buildCleanAirNoteText(bundle, mode, senderNote),
    [bundle, mode, senderNote]
  );

  if (!bundle) return null;

  const subjectLine =
    mode === "school"
      ? `Indoor Assembly / PE Request Today — ${bundle.air_snapshot.city_name} NAQI ${bundle.air_snapshot.current_naqi}`
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

      <div role="group" aria-label="Recipient type" className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          aria-pressed={mode === "school"}
          onClick={() => setMode("school")}
          className={`flex items-center gap-2 rounded-2xl px-3.5 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
            mode === "school"
              ? "bg-slate-900 text-white shadow-sm"
              : "bg-slate-100 text-slate-700 hover:bg-slate-200"
          }`}
        >
          <GraduationCap className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>For Child&apos;s School (Indoor Assembly/PE)</span>
        </button>

        <button
          type="button"
          aria-pressed={mode === "workplace"}
          onClick={() => setMode("workplace")}
          className={`flex items-center gap-2 rounded-2xl px-3.5 py-2.5 text-left text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
            mode === "workplace"
              ? "bg-slate-900 text-white shadow-sm"
              : "bg-slate-100 text-slate-700 hover:bg-slate-200"
          }`}
        >
          <Building2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>For Workplace / Outdoor Shift</span>
        </button>
      </div>

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
      </div>
    </Modal>
  );
}
