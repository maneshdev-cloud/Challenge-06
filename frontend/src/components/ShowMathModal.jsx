import React from "react";
import { X } from "lucide-react";

export default function ShowMathModal({ open, onClose, bundle }) {
  if (!open || !bundle) return null;

  const { air_snapshot, breathe_less, emit_less, provenance } = bundle;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm"
    >
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3.5">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-teal-700">
              Scientific Audit • Modeled Estimates Only
            </span>
            <h2 className="mt-0.5 text-lg font-extrabold text-slate-900">
              CPCB NAQI, USEPA Dosimetry, Boundary Layer &amp; ARAI Math
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 space-y-4 text-xs">
          {/* Atmospheric Physics */}
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-bold text-slate-900">
              1. Atmospheric Physics &amp; India CPCB NAQI
            </h3>
            <p className="mt-1 text-slate-700">
              PM2.5 mass concentration ({air_snapshot.current_pm25} ug/m3) and CPCB NAQI ({air_snapshot.current_naqi} •{" "}
              {air_snapshot.current_category}, dominant pollutant: {air_snapshot.dominant_pollutant}) are computed
              separately using CPCB linear breakpoints. Morning Planetary Boundary Layer Height (PBLH) ceiling:{" "}
              <strong>{air_snapshot.morning_inversion_ceiling_m} m</strong> ({air_snapshot.meteorology_regime}).
            </p>
          </div>

          {/* Ledger 1 Math */}
          <div className="rounded-2xl border border-teal-200 bg-teal-50/50 p-4">
            <h3 className="text-sm font-bold text-slate-900">
              2. Breathe Less — USEPA Inhaled Dose Proxy &amp; Berkeley Earth Equivalence
            </h3>
            <p className="mt-1.5 rounded-xl bg-white p-2.5 font-mono text-[11px] text-teal-900 ring-1 ring-teal-200">
              {breathe_less.formula_summary}
            </p>
            <ul className="mt-2.5 space-y-1 font-mono text-[11px] text-slate-700">
              {breathe_less.substitutions.map((s, idx) => (
                <li key={idx}>• {s}</li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-slate-600">
              <strong>Limitations:</strong> {breathe_less.limitations}
            </p>
          </div>

          {/* Ledger 2 Math */}
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-4">
            <h3 className="text-sm font-bold text-slate-900">
              3. Emit Less — ARAI / WRI India Transport Counterfactual
            </h3>
            <p className="mt-1.5 rounded-xl bg-white p-2.5 font-mono text-[11px] text-emerald-900 ring-1 ring-emerald-200">
              {emit_less.formula_summary}
            </p>
            <ul className="mt-2.5 space-y-1 font-mono text-[11px] text-slate-700">
              {emit_less.substitutions.map((s, idx) => (
                <li key={idx}>• {s}</li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-slate-600">
              <strong>Limitations:</strong> {emit_less.limitations}
            </p>
          </div>

          {/* Provenance */}
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-bold text-slate-900">4. Data Sources &amp; Provenance</h3>
            <p className="mt-1 text-slate-700">
              <strong>Source:</strong> {provenance.source} ({provenance.data_type})
            </p>
            <p className="mt-1 text-slate-700">
              <strong>Timestamp:</strong> {provenance.retrieved_at}
            </p>
            <p className="mt-1 text-slate-600">{provenance.spatial_note}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
