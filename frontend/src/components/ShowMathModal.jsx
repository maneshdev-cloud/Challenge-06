import { X } from "lucide-react";
import Modal from "./Modal";

export default function ShowMathModal({ open, onClose, bundle }) {
  if (!bundle) return null;

  const { air_snapshot, breathe_less, emit_less, provenance } = bundle;

  return (
    <Modal
      open={open}
      onClose={onClose}
      labelledBy="show-math-modal-title"
      maxWidthClass="max-w-2xl"
      panelClassName="max-h-[85vh] overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3.5">
        <div>
          <span className="text-[11px] font-bold uppercase tracking-wider text-teal-800">
            Scientific Audit • Modeled Estimates Only
          </span>
          <h2 id="show-math-modal-title" className="mt-0.5 text-lg font-extrabold text-slate-900">
            Estimated India NAQI, USEPA Dosimetry, PBLH &amp; ARAI Math
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close math modal"
          className="rounded-xl p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="mt-4 space-y-4 text-xs">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="text-sm font-bold text-slate-900">
            1. Atmospheric Physics &amp; Estimated India CPCB NAQI
          </h3>
          <p className="mt-1 text-slate-700">
            Modeled PM2.5 ({air_snapshot.current_pm25} ug/m3) and Estimated Hourly India CPCB NAQI (
            {air_snapshot.current_naqi} • {air_snapshot.current_category}, dominant pollutant:{" "}
            {air_snapshot.dominant_pollutant}) are mapped separately via CPCB linear breakpoints across{" "}
            <strong>3 of 8 CPCB criteria pollutants</strong> (PM2.5, PM10, NO2; excludes SO2, CO,
            O3, NH3, Pb) using satellite-assimilated CAMS Global forecasts (official CPCB NAQI is a
            24-hour station running average). Morning Planetary Boundary Layer Height (PBLH)
            ceiling: <strong>{air_snapshot.morning_inversion_ceiling_m} m</strong> (
            {air_snapshot.meteorology_regime}).
          </p>
        </div>

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
          <p className="mt-2 text-[11px] text-slate-700">
            <strong>Limitations:</strong> {breathe_less.limitations}
          </p>
        </div>

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
          <p className="mt-2 text-[11px] text-slate-700">
            <strong>Limitations:</strong> {emit_less.limitations}
          </p>
        </div>

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
    </Modal>
  );
}
