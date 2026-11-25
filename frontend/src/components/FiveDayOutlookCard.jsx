import React from "react";
import { CalendarDays, Clock } from "lucide-react";

function getTrafficLightStyle(naqi) {
  if (naqi <= 100) {
    return {
      card: "bg-gradient-to-b from-emerald-50 to-emerald-50/40 ring-emerald-300",
      pill: "bg-emerald-600 text-white"
    };
  }
  if (naqi <= 200) {
    return {
      card: "bg-gradient-to-b from-yellow-50 to-amber-50/50 ring-yellow-400",
      pill: "bg-yellow-400 text-slate-950"
    };
  }
  return {
    card: "bg-gradient-to-b from-rose-50 to-red-50/60 ring-red-300",
    pill: "bg-red-600 text-white"
  };
}

export default function FiveDayOutlookCard({ dailyOutlook }) {
  if (!dailyOutlook || dailyOutlook.length === 0) return null;

  return (
    <section className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-extrabold text-slate-900">
            <CalendarDays className="h-5 w-5 text-teal-700" />
            Next 5 Days Outlook
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Plan errands, school runs, and outdoor workouts across the week.
          </p>
        </div>
        <span className="rounded-full bg-teal-50 px-3 py-1 text-[11px] font-semibold text-teal-800 ring-1 ring-teal-200/70">
          5-Day Forecast
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {dailyOutlook.map((day) => {
          const style = getTrafficLightStyle(day.peak_naqi);
          return (
            <div
              key={day.date}
              className={`flex flex-col justify-between rounded-2xl p-3.5 ring-1 transition hover:shadow-sm ${style.card}`}
            >
              <div>
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-extrabold text-slate-900">{day.day_label}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${style.pill}`}>
                    {day.peak_category}
                  </span>
                </div>

                <p className="mt-2 font-mono text-xs font-bold tabular-nums text-slate-800">
                  Peak AQI {day.peak_naqi}{" "}
                  <span className="font-normal text-slate-600">({day.peak_pm25} ug/m3)</span>
                </p>

                <div className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-slate-800">
                  <Clock className="h-3 w-3 shrink-0 text-teal-700" />
                  <span className="truncate">Best: {day.best_window_label}</span>
                </div>
              </div>

              <p className="mt-2.5 border-t border-slate-900/10 pt-2 text-[11px] leading-snug text-slate-700">
                {day.tip}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
