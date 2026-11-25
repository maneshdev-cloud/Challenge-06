import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  HeartPulse,
  Leaf,
  MapPin,
  Shield,
  Smartphone
} from "lucide-react";
import { formatHourAmPm } from "../utils/formatters";

function heroTheme(category) {
  switch (category) {
    case "Good":
    case "Satisfactory":
      return {
        gradient: "from-emerald-700 via-teal-700 to-teal-900",
        badge: "bg-white/20 text-white ring-1 ring-white/30"
      };
    case "Moderate":
      return {
        gradient: "from-amber-700 via-orange-700 to-orange-900",
        badge: "bg-white/20 text-white ring-1 ring-white/30"
      };
    case "Poor":
      return {
        gradient: "from-orange-700 via-rose-700 to-rose-900",
        badge: "bg-white/20 text-white ring-1 ring-white/30"
      };
    case "Very Poor":
    case "Severe":
    default:
      return {
        gradient: "from-rose-800 via-red-900 to-slate-950",
        badge: "bg-white/15 text-white ring-1 ring-white/25"
      };
  }
}

export default function HeroAirCard({ bundle, onJumpToImpact }) {
  if (!bundle) return null;

  const { air_snapshot: air, breathe_less: bl, emit_less: el, provenance, profile_summary: prof } =
    bundle;
  const gw = air.golden_window;
  const theme = heroTheme(
    prof?.warning_active &&
      (air.current_category === "Good" ||
        air.current_category === "Satisfactory" ||
        air.current_category === "Moderate")
      ? air.current_naqi > 150
        ? "Poor"
        : "Moderate"
      : air.current_category
  );

  const locationTitle =
    air.area_name && air.area_name !== air.city_name
      ? `${air.area_name}, ${air.city_name}`
      : air.state
        ? `${air.city_name}, ${air.state}`
        : air.city_name;

  let headline = prof?.tailored_hero_headline || "";
  if (!headline) {
    if (gw.is_clean_air_day) {
      headline = "Air quality is Good/Satisfactory today — normal outdoor plans are fine.";
    } else if (gw.has_meaningful_window) {
      headline = `Best time outside today: ${formatHourAmPm(gw.start_hour)} – ${formatHourAmPm(
        gw.end_hour
      )} (${Math.round(gw.reduction_pct)}% cleaner than morning peak)`;
    } else {
      headline = "Air stays elevated all day — keep intense outdoor exercise indoors today.";
    }
  }

  const isPositiveDose = bl.dose_avoided_ug >= 0;
  const healthHeadline = isPositiveDose
    ? `${bl.reduction_pct}% less pollution breathed`
    : `${Math.abs(bl.reduction_pct)}% more pollution breathed`;
  const doseSub = isPositiveDose
    ? `-${bl.dose_avoided_ug} ug PM2.5`
    : `+${Math.abs(bl.dose_avoided_ug)} ug PM2.5`;

  const co2Headline =
    el.co2_saved_g >= 1000 ? `${el.co2_saved_kg} kg CO2 saved` : `${el.co2_saved_g} g CO2 saved`;
  const phoneCharges = Math.round(Math.max(0, el.co2_saved_g) / 8.2);

  return (
    <section
      aria-label="Live neighborhood air quality and daily guidance"
      className={`relative z-0 overflow-hidden rounded-3xl bg-gradient-to-br ${theme.gradient} p-5 text-white shadow-lg sm:p-7`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-white/95">
          <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{locationTitle}</span>
          {provenance?.is_fallback_replay && (
            <span className="ml-1 rounded-full bg-amber-300/25 px-2 py-0.5 text-[10px] font-bold text-amber-100 ring-1 ring-amber-200/40">
              Offline Replay
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {prof && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-extrabold ${
                prof.warning_active
                  ? "bg-amber-300 text-slate-950 shadow-sm"
                  : "bg-white/20 text-white ring-1 ring-white/30"
              }`}
            >
              {prof.warning_active && <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />}
              {prof.risk_badge}
            </span>
          )}
          <span className={`rounded-full px-3 py-1 text-xs font-bold ${theme.badge}`}>
            Outdoor: {air.current_category} Air
          </span>
        </div>
      </div>

      {/* Main Scannable Metrics + Headline */}
      <div className="mt-4 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex items-center gap-6">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-white/90">
              Est. India AQI
            </p>
            <p className="font-mono text-4xl font-extrabold tracking-tight tabular-nums sm:text-5xl">
              {air.current_naqi}
            </p>
          </div>
          <div className="h-11 w-px bg-white/30" />
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-white/90">
              Fine Dust (PM2.5)
            </p>
            <p className="font-mono text-2xl font-bold tabular-nums sm:text-3xl">
              {air.current_pm25} <span className="text-sm font-medium text-white/90">ug/m3</span>
            </p>
          </div>
        </div>

        <div className="max-w-lg">
          <div className="flex items-start gap-2 rounded-2xl bg-black/20 px-3.5 py-2.5 backdrop-blur-sm ring-1 ring-white/15">
            <Clock className="mt-0.5 h-4 w-4 shrink-0 text-white" aria-hidden="true" />
            <p className="text-sm font-semibold leading-snug text-white">{headline}</p>
          </div>
        </div>
      </div>

      {prof && (
        <div
          className={`mt-4 rounded-2xl px-4 py-3 backdrop-blur-sm ring-1 ${
            prof.warning_active
              ? "bg-amber-950/45 ring-amber-200/50"
              : "bg-black/25 ring-white/15"
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/20 px-2.5 py-0.5 font-extrabold text-white">
                <Shield className="h-3 w-3" aria-hidden="true" />
                {prof.profile_label}
              </span>
              <span className="text-[11px] font-semibold text-white/95">{prof.risk_level}</span>
            </div>
            <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] font-bold text-white">
              <span className="inline-flex items-center gap-1">
                <Activity className="h-3.5 w-3.5 text-emerald-200" aria-hidden="true" />
                Peak intake: {prof.peak_ventilation_m3_hr} m3/hr
              </span>
              <span>
                Daily lung load: {bl.optimized_dose_ug} ug
                {bl.baseline_dose_ug !== bl.optimized_dose_ug && ` (from ${bl.baseline_dose_ug} ug)`}
              </span>
            </div>
          </div>
          {prof.warning_banner && (
            <p className="mt-2 flex items-start gap-1.5 rounded-xl bg-black/25 px-3 py-2 text-xs font-semibold leading-snug text-white">
              {prof.warning_active && (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" aria-hidden="true" />
              )}
              <span>{prof.warning_banner}</span>
            </p>
          )}
          <p className="mt-1.5 text-xs leading-relaxed text-white/95">{prof.physiology_note}</p>
        </div>
      )}

      {/* Quick Human-Friendly + Scientific Impact Pills */}
      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          onClick={onJumpToImpact}
          className="inline-flex flex-wrap items-center gap-1.5 rounded-full bg-white px-3.5 py-1.5 text-xs font-bold text-slate-900 shadow-sm transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          <HeartPulse className="h-3.5 w-3.5 shrink-0 text-teal-700" aria-hidden="true" />
          <span className="whitespace-nowrap">{healthHeadline}</span>
          <span className="whitespace-nowrap font-mono text-[11px] font-semibold text-slate-600">
            ({doseSub})
          </span>
          <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-slate-600" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={onJumpToImpact}
          className="inline-flex flex-wrap items-center gap-1.5 rounded-full bg-black/25 px-3.5 py-1.5 text-xs font-bold text-white backdrop-blur-sm ring-1 ring-white/30 transition hover:bg-black/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          <Leaf className="h-3.5 w-3.5 shrink-0 text-emerald-200" aria-hidden="true" />
          <span className="whitespace-nowrap font-mono tabular-nums">
            {el.co2_saved_g > 0
              ? co2Headline
              : `${Math.round((prof?.total_outdoor_min || 60) / 60)}h work route protected`}
          </span>
          {phoneCharges > 0 && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-semibold text-white/95">
              • <Smartphone className="h-3 w-3" aria-hidden="true" /> ~{phoneCharges} phone charges
            </span>
          )}
          {el.tailpipe_pm25_saved_mg > 0 && (
            <span className="hidden whitespace-nowrap text-[11px] font-semibold text-white/95 sm:inline">
              • {el.tailpipe_pm25_saved_mg} mg less street soot
            </span>
          )}
        </button>
      </div>
    </section>
  );
}
