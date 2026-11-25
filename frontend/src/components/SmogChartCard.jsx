import { useEffect, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { ChevronLeft, ChevronRight, Clock, Wind } from "lucide-react";
import { formatHourAmPm } from "../utils/formatters";

const FIXED_6H_TICKS = ["00:00", "06:00", "12:00", "18:00"];

function CustomChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const pt = payload[0].payload;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/95 p-3 text-xs shadow-xl">
      <p className="font-bold text-slate-900">
        {pt.time_label} • <span className="text-teal-700">{pt.cpcb_category}</span>
      </p>
      <div className="mt-1.5 space-y-1 font-mono tabular-nums text-slate-700">
        <p>Fine Dust (PM2.5): <strong>{pt.pm2_5} ug/m3</strong></p>
        <p>Est. India AQI: <strong>{pt.cpcb_naqi}</strong> ({pt.dominant_pollutant})</p>
        <p>Air Mixing Height: <strong>{pt.boundary_layer_height} m</strong></p>
        <p>Wind Speed: <strong>{pt.wind_speed_10m} km/h</strong></p>
      </div>
    </div>
  );
}

const HOUR_META_DETAILS = {
  seniors: {
    good: (pt, naqi) => ({
      status: "Good",
      cue: "Gentle walk",
      detail: `Senior-safe window (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Gentle pace is fine; breathe calmly through the nose.`
    }),
    moderate: (pt, naqi) => ({
      status: "Caution",
      cue: "Slow + inhaler",
      detail: `Senior sensitive band (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Elevated for 65+/COPD lungs — keep walks brief & avoid traffic.`
    }),
    high: (pt, naqi) => ({
      status: naqi > 300 ? "Severe" : "Poor",
      cue: "Stay indoors",
      detail: `High senior airway risk (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Stay in your Sanctuary Room; use a fitted N95 for essential clinic trips.`
    })
  },
  delivery_riders: {
    good: (pt, naqi) => ({
      status: "Low Soot",
      cue: "Wear N95 roadside",
      detail: `Cleaner ambient backdrop (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Roadside 1.55x exhaust still accumulates over long shifts.`
    }),
    moderate: (pt, naqi) => ({
      status: "Road Smog",
      cue: "Wear N95",
      detail: `Road-plume warning (${pt.pm2_5} ug/m3 ambient -> ~${Math.round(pt.pm2_5 * 1.55)} ug/m3 roadside, Est. AQI ${naqi}): Wear fitted N95 on traffic shifts.`
    }),
    high: (pt, naqi) => ({
      status: naqi > 300 ? "Severe" : "Poor",
      cue: "N95 + breaks",
      detail: `Heavy tailpipe exposure (${pt.pm2_5} ug/m3 ambient, Est. AQI ${naqi}): Snug N95 mandatory on 2-wheeler; take breaks off busy junctions.`
    })
  },
  students_kids: {
    good: (pt, naqi) => ({
      status: "Good",
      cue: "Play OK",
      detail: `Good for kids & school sports (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Developing lungs absorb more per kg, so wait back from idling school buses.`
    }),
    moderate: (pt, naqi) => ({
      status: "Moderate",
      cue: "Light play only",
      detail: `Moderate air (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Pause heavy sprints for school kids; choose shaded inner parks.`
    }),
    high: (pt, naqi) => ({
      status: naqi > 300 ? "Severe" : "Poor",
      cue: "Indoor PE",
      detail: `High risk for kids (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Move school assembly & PE indoors; send an N95 for commute.`
    })
  },
  adults_commuters: {
    good: (pt, naqi) => ({
      status: naqi <= 50 ? "Good" : "Clean",
      cue: naqi <= 50 ? "Fresh air" : "Okay outdoors",
      detail: `Good / Satisfactory air (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Normal outdoor walks and errands are fine.`
    }),
    moderate: (pt, naqi) => ({
      status: "Moderate",
      cue: naqi > 150 ? "Limit intense" : "Short errands",
      detail: `Moderate pollution (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Keep outdoor errands brief and avoid busy traffic roads.`
    }),
    high: (pt, naqi) => ({
      status: naqi > 300 ? "Severe" : "Poor",
      cue: naqi > 300 ? "Stay indoors" : "Wear N95",
      detail: `${naqi > 300 ? "Heavy smog" : "Poor air"} (${pt.pm2_5} ug/m3, Est. AQI ${naqi}): Avoid outdoor workouts; wear a snug N95 for essential travel.`
    })
  }
};

function getHourMeta(pt, goldenHours, profileKey = "adults_commuters", warningThreshold = null) {
  const isGolden = goldenHours.includes(pt.hour);
  const naqi = pt.cpcb_naqi;
  const threshold = warningThreshold ?? (profileKey === "adults_commuters" ? 150 : 100);
  const pack = HOUR_META_DETAILS[profileKey] || HOUR_META_DETAILS.adults_commuters;

  // Green: <= 100 CPCB Good/Satisfactory band (synced cleanly across profiles & backend threshold)
  const bandKey = naqi <= 100 ? "good" : naqi <= 200 ? "moderate" : "high";
  const info = pack[bandKey](pt, naqi);

  if (bandKey === "good") {
    return {
      status: isGolden ? "Best" : info.status,
      cue: isGolden && profileKey !== "delivery_riders" ? "Best window" : info.cue,
      pillCls: "bg-emerald-700 text-white",
      cardTint: "from-emerald-100/90 to-emerald-50/70 ring-emerald-300",
      selectedRing: "ring-2 ring-emerald-800 shadow-md",
      detail: info.detail
    };
  }
  if (bandKey === "moderate") {
    const overThreshold = naqi > threshold;
    return {
      status: isGolden ? "Cleaner" : info.status,
      cue: isGolden ? "Lower dip" : overThreshold ? "Caution" : info.cue,
      pillCls: overThreshold ? "bg-amber-700 text-white" : "bg-yellow-400 text-slate-950",
      cardTint: "from-yellow-100/90 to-amber-50/75 ring-yellow-400",
      selectedRing: "ring-2 ring-amber-800 shadow-md",
      detail: info.detail
    };
  }
  return {
    status: info.status,
    cue: info.cue,
    pillCls: "bg-red-700 text-white",
    cardTint: "from-rose-100/95 to-red-50/80 ring-red-300",
    selectedRing: "ring-2 ring-red-800 shadow-md",
    detail: info.detail
  };
}

export default function SmogChartCard({ airSnapshot, profileSummary }) {
  const [selectedHour, setSelectedHour] = useState(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(true);
  const stripRef = useRef(null);

  function syncScrollEdges() {
    const el = stripRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 8);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 8);
  }

  function scrollStrip(direction) {
    const el = stripRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * 260, behavior: "smooth" });
  }

  useEffect(() => {
    if (!airSnapshot) return undefined;
    const clamped = Math.max(6, Math.min(22, airSnapshot.current_hour ?? 12));
    setSelectedHour(clamped);
    const t = setTimeout(syncScrollEdges, 80);
    return () => clearTimeout(t);
  }, [airSnapshot]);

  if (!airSnapshot) return null;

  const gw = airSnapshot.golden_window;
  const startLabel = `${String(gw.start_hour).padStart(2, "0")}:00`;
  const endLabel = `${String(Math.min(23, gw.end_hour)).padStart(2, "0")}:00`;

  const stripHours = airSnapshot.hourly.filter((pt) => pt.hour >= 6 && pt.hour <= 22);
  const activePt =
    stripHours.find((pt) => pt.hour === selectedHour) ||
    stripHours[0] ||
    airSnapshot.hourly[airSnapshot.current_hour];
  const profileKey = profileSummary?.profile_key || "adults_commuters";
  const warningThreshold = profileSummary?.warning_threshold_naqi;
  const activeMeta = activePt
    ? getHourMeta(activePt, gw.hours || [], profileKey, warningThreshold)
    : null;

  const pmValues = airSnapshot.hourly.map((pt) => pt.pm2_5);
  const minPm = Math.min(...pmValues);
  const maxPm = Math.max(...pmValues);
  const chartSummary = `24-hour PM2.5 and air mixing height chart for ${airSnapshot.city_name}. PM2.5 ranges from ${minPm} to ${maxPm} micrograms per cubic meter. Best daytime window: ${gw.window_label}. Morning mixing height: ${airSnapshot.morning_inversion_ceiling_m} meters.`;

  return (
    <section className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">
            Today&apos;s Air &amp; Best Time Outside
          </h2>
          <p className="mt-0.5 text-xs text-slate-600">{airSnapshot.meteorology_note}</p>
        </div>

        <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
          <Wind className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          {airSnapshot.meteorology_regime}
        </span>
      </div>

      {/* Plain-English Best Time Advisory */}
      <div
        className={`mt-4 rounded-2xl px-4 py-3 text-xs font-medium leading-relaxed ${
          gw.has_meaningful_window
            ? "bg-emerald-50 text-emerald-950 ring-1 ring-emerald-200/80"
            : "bg-amber-50 text-amber-950 ring-1 ring-amber-200/80"
        }`}
      >
        {gw.advisory}
      </div>

      {/* 24h Composed Chart with accessible description */}
      <div role="img" aria-label={chartSummary} className="mt-4 h-64 w-full sm:h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            accessibilityLayer
            data={airSnapshot.hourly}
            margin={{ top: 10, right: 10, left: -12, bottom: 0 }}
          >
            <defs>
              <linearGradient id="pm25Fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#e11d48" stopOpacity={0.26} />
                <stop offset="95%" stopColor="#e11d48" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="time_label"
              ticks={FIXED_6H_TICKS}
              tick={{ fontSize: 11, fill: "#475569" }}
            />
            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "#be123c" }} width={44} />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 11, fill: "#0f766e" }}
              width={44}
            />
            <Tooltip content={<CustomChartTooltip />} />
            <ReferenceArea
              yAxisId="left"
              x1={startLabel}
              x2={endLabel}
              fill={gw.has_meaningful_window ? "#10b981" : "#f59e0b"}
              fillOpacity={0.14}
              stroke={gw.has_meaningful_window ? "#059669" : "#d97706"}
              strokeDasharray="4 4"
            />
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="pm2_5"
              name="Fine Dust PM2.5 (ug/m3)"
              stroke="#e11d48"
              strokeWidth={2.5}
              fill="url(#pm25Fill)"
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="boundary_layer_height"
              name="Air Mixing Height (m)"
              stroke="#0f766e"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
        <div className="flex flex-wrap items-center gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-600" aria-hidden="true" /> Outdoor Dust (PM2.5 ug/m3)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 border-t-2 border-dashed border-teal-700" aria-hidden="true" /> Air Mixing Height (m)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded bg-emerald-200 ring-1 ring-emerald-500" aria-hidden="true" /> Best Daytime Window
          </span>
        </div>
        <span className="font-mono text-[11px] text-slate-700">
          Morning trap lid: {airSnapshot.morning_inversion_ceiling_m} m
        </span>
      </div>

      {/* Hour-by-Hour Breathable Air Strip (6 AM to 10 PM) without clipping overlays */}
      <div className="mt-5 border-t border-slate-100 pt-4">
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-700">
              Hour-by-Hour Air (6 AM – 10 PM)
            </h3>
            {profileSummary && (
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[10px] font-bold text-slate-700">
                {profileSummary.profile_label}
              </span>
            )}
            <span className="hidden items-center gap-2 text-[10px] font-bold sm:inline-flex">
              <span className="inline-flex items-center gap-1 text-emerald-700">
                <span className="h-2 w-2 rounded-full bg-emerald-700" aria-hidden="true" /> Good
              </span>
              <span className="inline-flex items-center gap-1 text-amber-800">
                <span className="h-2 w-2 rounded-full bg-amber-600" aria-hidden="true" /> Moderate
              </span>
              <span className="inline-flex items-center gap-1 text-red-700">
                <span className="h-2 w-2 rounded-full bg-red-700" aria-hidden="true" /> Poor/Worst
              </span>
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={!canScrollLeft}
              onClick={() => scrollStrip(-1)}
              aria-label="Scroll earlier hours"
              className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-35"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              disabled={!canScrollRight}
              onClick={() => scrollStrip(1)}
              aria-label="Scroll later hours"
              className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-35"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div
          ref={stripRef}
          onScroll={syncScrollEdges}
          className="flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-1 py-1.5"
        >
          {stripHours.map((pt) => {
            const meta = getHourMeta(pt, gw.hours || [], profileKey, warningThreshold);
            const isSelected = activePt?.hour === pt.hour;
            const shortTime = formatHourAmPm(pt.hour).replace(":00 ", " ");
            return (
              <button
                key={pt.hour}
                type="button"
                aria-pressed={isSelected}
                aria-label={`${formatHourAmPm(pt.hour)}, ${meta.status}, PM2.5 ${pt.pm2_5} ug/m3, Est. AQI ${pt.cpcb_naqi}`}
                onClick={() => setSelectedHour(pt.hour)}
                className={`flex w-32 shrink-0 snap-start flex-col justify-between rounded-2xl bg-gradient-to-b ${meta.cardTint} p-2.5 text-left ring-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${
                  isSelected ? meta.selectedRing : "hover:brightness-95"
                }`}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="whitespace-nowrap font-mono text-xs font-extrabold text-slate-900">
                    {shortTime}
                  </span>
                  <span
                    className={`whitespace-nowrap rounded-full px-1.5 py-0.5 text-[10px] font-bold ${meta.pillCls}`}
                  >
                    {meta.status}
                  </span>
                </div>

                <div className="mt-2 whitespace-nowrap font-mono text-[11px] tabular-nums text-slate-800">
                  <span className="font-bold text-slate-950">{pt.pm2_5}</span> ug • AQI{" "}
                  <span className="font-bold">{pt.cpcb_naqi}</span>
                </div>

                <p className="mt-1 whitespace-nowrap text-[11px] font-semibold text-slate-800">
                  {meta.cue}
                </p>
              </button>
            );
          })}
        </div>

        {activePt && activeMeta && (
          <div
            aria-live="polite"
            className="mt-2.5 flex items-start gap-2 rounded-2xl bg-slate-900 px-3.5 py-2.5 text-xs text-slate-100"
          >
            <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal-300" aria-hidden="true" />
            <span>
              <strong className="text-white">{formatHourAmPm(activePt.hour)}:</strong>{" "}
              {activeMeta.detail}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
