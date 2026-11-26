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
import { Wind } from "lucide-react";
import HourlySlotStrip from "./HourlySlotStrip";

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

export default function SmogChartCard({ airSnapshot, profileSummary }) {
  if (!airSnapshot) return null;

  const gw = airSnapshot.golden_window;
  const startLabel = `${String(gw.start_hour).padStart(2, "0")}:00`;
  const endLabel = `${String(Math.min(23, gw.end_hour)).padStart(2, "0")}:00`;
  const pmValues = airSnapshot.hourly.map((pt) => pt.pm2_5);
  const minPm = Math.min(...pmValues);
  const maxPm = Math.max(...pmValues);
  const chartSummary = `24-hour PM2.5 and air mixing height chart for ${airSnapshot.city_name}. PM2.5 ranges from ${minPm} to ${maxPm} micrograms per cubic meter. Best daytime window: ${gw.window_label}. Morning mixing height: ${airSnapshot.morning_inversion_ceiling_m} meters.`;

  return (
    <section className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Today&apos;s Air &amp; Best Time Outside</h2>
          <p className="mt-0.5 text-xs text-slate-600">{airSnapshot.meteorology_note}</p>
        </div>

        <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
          <Wind className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          {airSnapshot.meteorology_regime}
        </span>
      </div>

      <div
        className={`mt-4 rounded-2xl px-4 py-3 text-xs font-medium leading-relaxed ${
          gw.has_meaningful_window
            ? "bg-emerald-50 text-emerald-950 ring-1 ring-emerald-200/80"
            : "bg-amber-50 text-amber-950 ring-1 ring-amber-200/80"
        }`}
      >
        {gw.advisory}
      </div>

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
            <XAxis dataKey="time_label" ticks={FIXED_6H_TICKS} tick={{ fontSize: 11, fill: "#475569" }} />
            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "#be123c" }} width={44} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: "#0f766e" }} width={44} />
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

      <HourlySlotStrip airSnapshot={airSnapshot} profileSummary={profileSummary} />
    </section>
  );
}
