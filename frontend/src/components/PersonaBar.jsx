import { useEffect, useRef, useState } from "react";
import {
  Bike,
  Briefcase,
  ChevronDown,
  GraduationCap,
  HeartHandshake,
  SlidersHorizontal,
  Sparkles
} from "lucide-react";

const USER_CATEGORIES = [
  { id: "students_kids", label: "Students & Kids", Icon: GraduationCap },
  { id: "adults_commuters", label: "Adults & Commuters", Icon: Briefcase },
  { id: "seniors", label: "Seniors", Icon: HeartHandshake },
  { id: "delivery_riders", label: "Delivery Riders", Icon: Bike }
];

export default function PersonaBar({
  activeCategoryId,
  onSelectCategory,
  presets,
  activePresetId,
  onSelectPreset,
  onOpenCustomizer
}) {
  const [presetOpen, setPresetOpen] = useState(false);
  const presetRef = useRef(null);

  useEffect(() => {
    function handleOutside(e) {
      if (presetRef.current && !presetRef.current.contains(e.target)) {
        setPresetOpen(false);
      }
    }
    function handleEscape(e) {
      if (e.key === "Escape") setPresetOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  return (
    <section
      aria-label="User category and quick demo presets"
      className="flex flex-wrap items-center justify-between gap-2"
    >
      <div
        role="group"
        aria-label="Household profile category"
        className="no-scrollbar flex flex-1 items-center gap-2 overflow-x-auto pb-1"
      >
        {USER_CATEGORIES.map(({ id, label, Icon }) => {
          const isActive = activeCategoryId === id;
          return (
            <button
              key={id}
              type="button"
              aria-pressed={isActive}
              onClick={() => onSelectCategory(id)}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                isActive
                  ? "bg-gradient-to-r from-slate-900 to-teal-900 text-white shadow-sm"
                  : "bg-white text-slate-700 shadow-sm ring-1 ring-slate-200/80 hover:bg-teal-50/60"
              }`}
            >
              <Icon
                className={`h-3.5 w-3.5 ${isActive ? "text-teal-300" : "text-teal-700"}`}
                aria-hidden="true"
              />
              <span>{label}</span>
            </button>
          );
        })}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div ref={presetRef} className="relative">
          <button
            type="button"
            aria-expanded={presetOpen}
            aria-haspopup="menu"
            onClick={() => setPresetOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-2 text-xs font-semibold text-teal-900 ring-1 ring-teal-200/80 transition hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <Sparkles className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
            <span className="hidden sm:inline">Quick Demo Presets</span>
            <span className="sm:hidden">Demos</span>
            <ChevronDown className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          </button>

          {presetOpen && (
            <div
              role="menu"
              aria-label="1-Click Benchmark Personas"
              className="absolute right-0 top-11 z-40 w-72 rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl"
            >
              <p className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-600">
                1-Click Benchmark Personas
              </p>
              <div className="mt-1 space-y-1">
                {presets.map((p) => {
                  const active = activePresetId === p.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        onSelectPreset(p);
                        setPresetOpen(false);
                      }}
                      className={`w-full rounded-xl px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                        active ? "bg-slate-900 text-white" : "hover:bg-slate-100"
                      }`}
                    >
                      <p className="text-xs font-bold">{p.label}</p>
                      <p
                        className={`mt-0.5 text-[11px] ${
                          active ? "text-slate-300" : "text-slate-600"
                        }`}
                      >
                        {p.short_tag}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onOpenCustomizer}
          className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200/80 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <SlidersHorizontal className="h-3.5 w-3.5 text-teal-700" aria-hidden="true" />
          <span className="hidden sm:inline">Edit Household</span>
          <span className="sm:hidden">Edit</span>
        </button>
      </div>
    </section>
  );
}
