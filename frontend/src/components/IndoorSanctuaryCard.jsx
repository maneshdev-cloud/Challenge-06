import React from "react";
import {
  Activity,
  AlertCircle,
  DoorOpen,
  Droplets,
  HeartPulse,
  Home,
  Info,
  ShieldAlert,
  Wind
} from "lucide-react";
import { formatHourAmPm } from "../utils/formatters";
import RoomAuditCard from "./RoomAuditCard";

export default function IndoorSanctuaryCard({
  sanctuaryPlan,
  currentNaqi = 150,
  currentCategory = "Moderate",
  city = "mumbai",
  areaName = null,
  language = "en",
  onOpenPermissions
}) {
  if (!sanctuaryPlan) return null;

  const wa = sanctuaryPlan.window_advice;
  const highSmog = currentNaqi > 200;

  const wellnessTips = [
    {
      title: "Gentle Yoga & Nasal Pranayama",
      detail: `Practice slow restorative poses and calm nasal breathing inside ${sanctuaryPlan.sanctuary_room} to keep breathing rate low.`,
      Icon: Wind
    },
    {
      title: "Light Indoor Mobility",
      detail: "Do 10-15 minutes of hallway walking, shoulder/hip mobility, or light resistance stretches away from the kitchen.",
      Icon: Activity
    },
    {
      title: "Hydration & Saline Rinse",
      detail: "Sip warm water through the day and rinse face/nose with plain water or saline after returning from traffic.",
      Icon: Droplets
    },
    {
      title: highSmog ? "Pause Heavy Cardio Today" : "Watch Breathing Intensity",
      detail: highSmog
        ? `AQI is ${currentNaqi} (${currentCategory})—avoid intense HIIT or vigorous cardio indoors/outdoors today because heavy breathing pulls 3-4x more fine dust.`
        : "Keep intense cardio moderate indoors when windows are shut; shift outdoor runs to the lower-exposure slot.",
      Icon: HeartPulse,
      highlight: highSmog
    }
  ];

  return (
    <section className="space-y-5">
      <div className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">
            Safest Room &amp; Home Air Plan
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Zero-cost kitchen, mopping, and window habits to keep indoor dust low.
          </p>
        </div>

        {/* Clean Air Sanctuary Spotlight */}
        <div className="mt-4 rounded-2xl bg-gradient-to-br from-teal-50 via-emerald-50/40 to-white p-4 ring-1 ring-teal-200/70">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-700 text-white shadow-sm">
                <Home className="h-5 w-5" />
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wide text-teal-800">
                  Safest Room in Your Home
                </p>
                <p className="text-base font-extrabold text-slate-900">
                  {sanctuaryPlan.sanctuary_room}
                </p>
              </div>
            </div>
            <span className="rounded-full bg-white px-3 py-1 font-mono text-xs font-bold text-teal-900 shadow-sm ring-1 ring-teal-200">
              Score {sanctuaryPlan.room_scores[0]?.score ?? "--"}/100
            </span>
          </div>

          <div className="mt-3.5 space-y-2">
            {sanctuaryPlan.room_scores.map((rm) => (
              <div key={rm.name} className="rounded-xl bg-white/95 px-3.5 py-2.5 text-xs ring-1 ring-slate-200/70">
                <div className="flex items-center justify-between font-bold text-slate-800">
                  <span className="flex items-center gap-2">
                    {rm.name}
                    {rm.is_sanctuary && (
                      <span className="rounded-full bg-teal-100 px-2 py-0.5 text-[10px] font-bold text-teal-800">
                        Safest
                      </span>
                    )}
                  </span>
                  <span className="font-mono tabular-nums">{rm.score}/100</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${rm.is_sanctuary ? "bg-teal-600" : "bg-slate-400"
                      }`}
                    style={{ width: `${Math.max(10, Math.min(100, rm.score))}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] text-slate-500">{rm.reason}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Window Timer Protocol */}
        <div className="mt-4 rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
              <DoorOpen className="h-4 w-4 text-teal-700" />
              <span>
                {wa.action === "timed_open"
                  ? `Open Windows 20 Min (${formatHourAmPm(wa.open_window_start_hour)} – ${formatHourAmPm(
                    wa.open_window_end_hour
                  )})`
                  : "Keep Street Windows Shut + Exhaust Kitchen Smoke"}
              </span>
            </div>
            <span className="font-mono text-[11px] text-slate-500">
              Out min {wa.outdoor_min_pm25} vs In ~{wa.modeled_indoor_baseline_pm25} ug/m3
            </span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-700">{wa.guidance}</p>
        </div>

        {/* Personalized Household Alerts */}
        {sanctuaryPlan.personalized_alerts?.length > 0 && (
          <div className="mt-3 space-y-2">
            {sanctuaryPlan.personalized_alerts.map((alert, i) => (
              <div
                key={i}
                className="flex items-start gap-2 rounded-2xl bg-amber-50 px-3.5 py-2.5 text-xs font-medium text-amber-950 ring-1 ring-amber-200"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
                <span>{alert}</span>
              </div>
            ))}
          </div>
        )}

        {/* Budget-Tiered Home Checklist */}
        <div className="mt-5">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Practical Home Actions (Free Habits First)
          </h3>
          <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {sanctuaryPlan.applicable_hacks.map((hack) => (
              <div
                key={hack.id}
                className="rounded-2xl bg-gradient-to-br from-slate-50 to-white p-3.5 ring-1 ring-slate-200/70 transition hover:shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-bold text-slate-900">{hack.title}</span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${hack.max_cost_inr === 0
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-sky-100 text-sky-800"
                      }`}
                  >
                    {hack.tier}
                  </span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-700">{hack.action}</p>
                <p className="mt-1.5 text-[11px] font-semibold text-teal-700">{hack.impact_note}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Safety Notes */}
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="flex items-start gap-2 rounded-2xl bg-slate-100 px-3.5 py-2.5 text-[11px] text-slate-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-slate-700" />
            <span>
              <strong>Fresh Air Safety:</strong> {sanctuaryPlan.co2_safety_note}
            </span>
          </div>
          <div className="flex items-start gap-2 rounded-2xl bg-slate-100 px-3.5 py-2.5 text-[11px] text-slate-700">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-slate-700" />
            <span>
              <strong>Myth Check:</strong> {sanctuaryPlan.no_houseplants_note}
            </span>
          </div>
        </div>
      </div>

      {/* Multimodal Gemini Vision Room IAQ Audit */}
      <RoomAuditCard
        city={city}
        areaName={areaName}
        language={language}
        currentNaqi={currentNaqi}
        onOpenPermissions={onOpenPermissions}
      />

      {/* Stay Active Indoors Practical Wellness Card */}
      <div className="rounded-3xl bg-gradient-to-br from-indigo-50/70 via-white to-teal-50/70 p-5 shadow-md shadow-slate-200/60 ring-1 ring-indigo-200/60 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-extrabold text-slate-900">Stay Active Indoors</h3>
            <p className="mt-0.5 text-xs text-slate-600">
              Air-safe movement and recovery habits when outdoor smog keeps workouts inside.
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-[11px] font-bold ${highSmog ? "bg-rose-100 text-rose-900" : "bg-teal-100 text-teal-900"
              }`}
          >
            {highSmog ? "Low-Intensity Recommended" : "Light Indoor Wellness"}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {wellnessTips.map(({ title, detail, Icon, highlight }) => (
            <div
              key={title}
              className={`rounded-2xl p-3.5 ring-1 transition ${highlight
                  ? "bg-rose-50/80 ring-rose-200"
                  : "bg-white/90 ring-slate-200/70"
                }`}
            >
              <div className="flex items-center gap-2">
                <div
                  className={`flex h-7 w-7 items-center justify-center rounded-lg ${highlight ? "bg-rose-100 text-rose-700" : "bg-teal-50 text-teal-700"
                    }`}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <span className="text-xs font-bold text-slate-900">{title}</span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-600">{detail}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
