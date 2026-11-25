import React, { useState } from "react";
import { AlertTriangle, Calculator, ChevronDown, ChevronUp, Database, Radio, ShieldCheck } from "lucide-react";
import { formatTimeIst } from "../utils/formatters";

export default function DataFooter({
  provenance,
  simulateStale,
  onToggleStale,
  onOpenMath,
  onOpenAppPermissions
}) {
  const [expanded, setExpanded] = useState(false);
  const isFallback = provenance?.is_stale || provenance?.is_fallback_replay || simulateStale;

  return (
    <footer className="mt-8 rounded-2xl border border-slate-200/90 bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <Radio className={`h-3.5 w-3.5 ${isFallback ? "text-amber-600" : "text-emerald-600"}`} />
          <span className="font-semibold text-slate-800">
            {isFallback
              ? "Offline Historical Replay Active"
              : `Live Open-Meteo Forecast • ${provenance?.retrieved_at ? `${formatTimeIst(provenance.retrieved_at)} IST` : "Ready"}`}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200"
        >
          <Database className="h-3.5 w-3.5 text-slate-500" />
          <span>Data &amp; Judge Mode</span>
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-100 pt-3 text-xs text-slate-600">
          {provenance && (
            <div className="rounded-xl bg-slate-50 p-3">
              <p>
                <strong>Data Source:</strong> {provenance.source} ({provenance.data_type})
              </p>
              <p className="mt-1 text-slate-500">{provenance.spatial_note}</p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onToggleStale}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                simulateStale
                  ? "border-amber-400 bg-amber-50 text-amber-900"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              <AlertTriangle className={`h-3.5 w-3.5 ${simulateStale ? "text-amber-600" : "text-slate-400"}`} />
              {simulateStale ? "Simulate Stale Data: ON" : "Simulate Stale Data"}
            </button>

            <button
              type="button"
              onClick={onOpenMath}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Calculator className="h-3.5 w-3.5 text-teal-700" />
              Show Math &amp; Sources
            </button>

            {onOpenAppPermissions && (
              <button
                type="button"
                onClick={onOpenAppPermissions}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                <ShieldCheck className="h-3.5 w-3.5 text-teal-700" />
                Install App &amp; Phone Permissions
              </button>
            )}
          </div>
        </div>
      )}
    </footer>
  );
}
