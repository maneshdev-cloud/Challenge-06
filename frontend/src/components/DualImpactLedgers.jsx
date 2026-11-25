import {
  ArrowRight,
  Calculator,
  Car,
  Cigarette,
  HeartPulse,
  Leaf,
  RotateCcw,
  Sliders,
  Smartphone
} from "lucide-react";
import { TRANSPORT_MODES } from "../data/constants";
import { formatHourAmPm } from "../utils/formatters";

export default function DualImpactLedgers({
  breatheLess,
  emitLess,
  goldenStartHour,
  walkOverrideHour,
  onWalkHourChange,
  onResetWalkHour,
  targetCommuteMode,
  onTargetCommuteChange,
  commuteKm,
  onCommuteKmChange,
  onOpenMath
}) {
  if (!breatheLess || !emitLess) return null;

  const sliderHour = walkOverrideHour ?? goldenStartHour ?? 14;
  const isPositiveDose = breatheLess.dose_avoided_ug >= 0;
  const lowSmogCigs = breatheLess.cigarettes_avoided >= 0 && breatheLess.cigarettes_avoided < 0.2;
  const phoneCharges =
    emitLess.phone_charges_saved ?? Math.round(Math.max(0, emitLess.co2_saved_g) / 8.2);

  return (
    <section className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">
            Your Health &amp; Climate Savings
          </h2>
          <p className="mt-0.5 text-xs text-slate-600">
            Test different walk times or commute options to see live modeled savings.
          </p>
        </div>

        <button
          type="button"
          onClick={onOpenMath}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3.5 py-2 text-xs font-bold text-slate-800 transition hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <Calculator className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          Show Math &amp; Sources
        </button>
      </div>

      {/* Two Strictly Separated Impact Cards */}
      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Ledger 1: Breathe Less */}
        <div className="rounded-2xl bg-gradient-to-br from-teal-50/90 to-white p-5 ring-1 ring-teal-200/80">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <HeartPulse className="h-5 w-5 text-teal-700" aria-hidden="true" />
              <h3 className="text-sm font-extrabold text-slate-900">Breathe Less (Health)</h3>
            </div>
            <span className="rounded-full bg-teal-100 px-2.5 py-0.5 text-[10px] font-bold uppercase text-teal-900">
              {breatheLess.label}
            </span>
          </div>

          <div className="mt-3.5">
            <p
              className={`text-2xl font-extrabold tracking-tight sm:text-3xl ${isPositiveDose ? "text-teal-800" : "text-rose-700"
                }`}
            >
              {isPositiveDose
                ? `${breatheLess.reduction_pct}% less pollution breathed`
                : `${Math.abs(breatheLess.reduction_pct)}% more pollution breathed`}
            </p>
            <p className="mt-1 whitespace-nowrap font-mono text-xs font-bold text-slate-700">
              {isPositiveDose
                ? `-${breatheLess.dose_avoided_ug} ug fine dust (PM2.5) avoided`
                : `+${Math.abs(breatheLess.dose_avoided_ug)} ug fine dust (PM2.5) added`}
            </p>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-white p-3 text-center font-mono text-xs tabular-nums ring-1 ring-slate-200/80">
            <div>
              <p className="font-sans text-[10px] font-semibold uppercase text-slate-600">Before</p>
              <p className="mt-0.5 whitespace-nowrap font-bold text-slate-700">
                {breatheLess.baseline_dose_ug} ug PM2.5
              </p>
            </div>
            <div>
              <p className="font-sans text-[10px] font-semibold uppercase text-slate-600">After</p>
              <p className="mt-0.5 whitespace-nowrap font-bold text-teal-800">
                {breatheLess.optimized_dose_ug} ug PM2.5
              </p>
            </div>
          </div>

          <div className="mt-2.5 flex items-center gap-2 rounded-xl bg-teal-50/70 px-3 py-2 text-xs text-teal-950 ring-1 ring-teal-200/60">
            <Cigarette className="h-4 w-4 shrink-0 text-teal-700" aria-hidden="true" />
            <span className="font-semibold">
              <span className="font-mono font-bold">{breatheLess.cigarettes_avoided}</span>{" "}
              cigarette equivalents avoided today (330 ug/cig)
              {lowSmogCigs ? " • Low-smog day" : ""}
            </span>
          </div>
        </div>

        {/* Ledger 2: Emit Less */}
        <div className="rounded-2xl bg-gradient-to-br from-emerald-50/90 to-white p-5 ring-1 ring-emerald-200/80">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Leaf className="h-5 w-5 text-emerald-700" aria-hidden="true" />
              <h3 className="text-sm font-extrabold text-slate-900">Emit Less (Emissions)</h3>
            </div>
            <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-[10px] font-bold uppercase text-emerald-900">
              {emitLess.label}
            </span>
          </div>

          <div className="mt-3.5 flex flex-wrap items-baseline gap-2.5">
            <span className="whitespace-nowrap font-mono text-2xl font-extrabold tabular-nums text-emerald-800 sm:text-3xl">
              {emitLess.co2_saved_g >= 1000
                ? `${emitLess.co2_saved_kg} kg`
                : `${emitLess.co2_saved_g} g`}{" "}
              <span className="text-sm font-bold">CO2 saved</span>
            </span>
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-white px-2.5 py-1 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200">
              {emitLess.tailpipe_pm25_saved_mg} mg less street soot
            </span>
          </div>

          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {phoneCharges > 0 ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100/80 px-3 py-1 text-xs font-bold text-emerald-900">
                <Smartphone className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
                ~{phoneCharges} smartphone charges
              </span>
            ) : (
              <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                Same travel mode kept
              </span>
            )}
            <span className="font-mono text-[11px] text-slate-600">
              ({emitLess.co2_saved_g} g CO2e • -{emitLess.tailpipe_pm25_saved_mg} mg tailpipe PM2.5)
            </span>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white px-3.5 py-3 text-xs ring-1 ring-slate-200/80">
            <div className="flex items-center gap-2 text-slate-700">
              <Car className="h-4 w-4 text-slate-500" aria-hidden="true" />
              <span className="font-medium">{emitLess.baseline_mode_label}</span>
            </div>
            <div className="flex items-center gap-1.5 font-bold text-emerald-800">
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{emitLess.target_mode_label}</span>
            </div>
          </div>

          <p className="mt-3 text-[11px] leading-relaxed text-slate-600">
            Daily travel emissions avoided across {emitLess.commute_km} km of commuting.
          </p>
        </div>
      </div>

      {/* Interactive What-If Sliders */}
      <div className="mt-5 rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sliders className="h-4 w-4 text-teal-700" aria-hidden="true" />
            <h3 className="text-xs font-extrabold uppercase tracking-wide text-slate-700">
              Try What-If Changes
            </h3>
          </div>
          {walkOverrideHour !== null && (
            <button
              type="button"
              onClick={onResetWalkHour}
              className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-teal-800 ring-1 ring-slate-200 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <RotateCcw className="h-3 w-3" aria-hidden="true" /> Reset Best Hour
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <div>
            <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
              <label htmlFor="walk-hour-slider">Test Walk / Play Hour</label>
              <span className="font-mono font-bold text-teal-800">{formatHourAmPm(sliderHour)}</span>
            </div>
            <input
              id="walk-hour-slider"
              type="range"
              min={5}
              max={21}
              step={1}
              value={sliderHour}
              aria-valuetext={formatHourAmPm(sliderHour)}
              onChange={(e) => onWalkHourChange(Number(e.target.value))}
              className="mt-2.5 w-full accent-teal-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            />
            <div className="flex justify-between text-[10px] text-slate-600">
              <span>5 AM</span>
              <span>2 PM</span>
              <span>9 PM</span>
            </div>
          </div>

          <div>
            <label
              htmlFor="commute-mode-select"
              className="block text-xs font-semibold text-slate-700"
            >
              Switch Commute Mode
            </label>
            <select
              id="commute-mode-select"
              value={targetCommuteMode}
              onChange={(e) => onTargetCommuteChange(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-900 focus:border-teal-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              {TRANSPORT_MODES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
              <label htmlFor="commute-km-slider">Daily Travel Distance</label>
              <span className="font-mono font-bold text-emerald-800">{commuteKm} km</span>
            </div>
            <input
              id="commute-km-slider"
              type="range"
              min={0}
              max={60}
              step={2}
              value={commuteKm}
              aria-valuetext={`${commuteKm} kilometers`}
              onChange={(e) => onCommuteKmChange(Number(e.target.value))}
              className="mt-2.5 w-full accent-emerald-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
            />
            <div className="flex justify-between text-[10px] text-slate-600">
              <span>0 km</span>
              <span>30 km</span>
              <span>60 km</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
