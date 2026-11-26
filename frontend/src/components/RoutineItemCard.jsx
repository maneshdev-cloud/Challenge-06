import { ArrowRight, CheckCircle2, Clock, Shield } from "lucide-react";
import { formatHourAmPm } from "../utils/formatters";

export function friendlyBadge(badge) {
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

export default function RoutineItemCard({ item }) {
  const b = friendlyBadge(item.badge);

  return (
    <div className="rounded-2xl bg-gradient-to-br from-slate-50/90 to-white p-4 ring-1 ring-slate-200/80 transition-all duration-200 hover:shadow-md">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${b.cls}`}>
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
                <span className="text-slate-600 line-through">{formatHourAmPm(item.original_hour)}</span>
                <ArrowRight className="h-3 w-3 text-emerald-700" aria-hidden="true" />
                <span className="text-emerald-800">{formatHourAmPm(item.recommended_hour)}</span>
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
            item.dose_avoided_ug >= 0 ? "bg-emerald-100 text-emerald-900" : "bg-rose-100 text-rose-900"
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
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal-700" aria-hidden="true" />
            <span>{step}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
