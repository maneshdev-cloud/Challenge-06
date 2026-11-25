import { useState } from "react";
import { Loader2, Plus, RotateCcw, Trash2, UserPlus, X } from "lucide-react";
import Modal from "./Modal";

const CONDITIONS = [
  { key: "adult", label: "Adult" },
  { key: "child", label: "Child" },
  { key: "asthma", label: "Asthma" },
  { key: "elderly", label: "Senior" },
  { key: "copd", label: "COPD / Cardiac" },
  { key: "outdoor_worker", label: "Outdoor Worker" }
];

export default function HouseholdCustomizer({
  open,
  onClose,
  planConfig,
  onUpdateConfig,
  onResetSaved,
  saving
}) {
  const [newMemberName, setNewMemberName] = useState("");
  const [newMemberAge, setNewMemberAge] = useState(28);
  const [newMemberCond, setNewMemberCond] = useState("adult");

  const [newActName, setNewActName] = useState("");
  const [newActFlex, setNewActFlex] = useState("flexible");
  const [newActHour, setNewActHour] = useState(7);
  const [newActMember, setNewActMember] = useState("");

  if (!planConfig) return null;

  function addMember(e) {
    e.preventDefault();
    if (!newMemberName.trim()) return;
    const member = {
      name: newMemberName.trim(),
      age: Number(newMemberAge) || 25,
      conditions: [newMemberCond]
    };
    onUpdateConfig({
      ...planConfig,
      preset_id: null,
      members: [...planConfig.members, member]
    });
    setNewMemberName("");
  }

  function removeMember(idx) {
    if (planConfig.members.length <= 1) return;
    const removed = planConfig.members[idx];
    const remaining = planConfig.members.filter((_, i) => i !== idx);
    const fallbackName = remaining[0]?.name || "Household Member";
    const updatedActivities = planConfig.activities.map((a) =>
      a.member_name === removed.name ? { ...a, member_name: fallbackName } : a
    );
    onUpdateConfig({
      ...planConfig,
      preset_id: null,
      members: remaining,
      activities: updatedActivities
    });
  }

  function addActivity(e) {
    e.preventDefault();
    if (!newActName.trim()) return;
    const chosenMember = newActMember || planConfig.members[0]?.name || "Household Member";
    const item = {
      id: `custom_${Date.now()}`,
      name: newActName.trim(),
      flexibility: newActFlex,
      planned_hour: Number(newActHour),
      duration_min: 30,
      activity_level: "light_walk",
      member_name: chosenMember,
      current_mask: "none",
      is_commute: false,
      is_work_shift: false
    };
    onUpdateConfig({
      ...planConfig,
      preset_id: null,
      activities: [...planConfig.activities, item]
    });
    setNewActName("");
  }

  function removeActivity(id) {
    if (planConfig.activities.length <= 1) return;
    onUpdateConfig({
      ...planConfig,
      preset_id: null,
      activities: planConfig.activities.filter((a) => a.id !== id)
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      labelledBy="household-customizer-title"
      maxWidthClass="max-w-2xl"
      panelClassName="max-h-[90vh] overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-slate-200 pb-3.5">
        <div>
          <h2 id="household-customizer-title" className="text-base font-extrabold text-slate-900">
            Edit Household &amp; Daily Tasks
          </h2>
          <p className="text-xs text-slate-600">
            Saved automatically in your browser so your family setup persists across reloads.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close household editor"
          className="rounded-xl p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="mt-5 space-y-5">
        {/* Budget & Indoor Habits */}
        <div className="rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">
            Budget &amp; Home Habits
          </h3>
          <div className="mt-3 space-y-3">
            <div>
              <label
                htmlFor="budget-tier-select"
                className="block text-xs font-semibold text-slate-700"
              >
                Filter &amp; Mask Budget
              </label>
              <select
                id="budget-tier-select"
                value={planConfig.budget_tier}
                onChange={(e) =>
                  onUpdateConfig({ ...planConfig, preset_id: null, budget_tier: e.target.value })
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-900 focus:border-teal-600 focus:outline-none"
              >
                <option value="rs_0">Rs 0 (Free Home Habits Only)</option>
                <option value="under_500">Under Rs 500 (N95 Mask + Window Seal Tape)</option>
                <option value="under_2200">Under Rs 2,200 (DIY Box Fan + HEPA Filter)</option>
              </select>
            </div>

            <label className="flex items-center gap-2.5 text-xs font-medium text-slate-700">
              <input
                type="checkbox"
                checked={planConfig.uses_agarbatti_or_coils}
                onChange={(e) =>
                  onUpdateConfig({
                    ...planConfig,
                    preset_id: null,
                    uses_agarbatti_or_coils: e.target.checked
                  })
                }
                className="h-4 w-4 rounded accent-teal-600"
              />
              Uses agarbatti, dhoop, or mosquito coils indoors
            </label>

            <label className="flex items-center gap-2.5 text-xs font-medium text-slate-700">
              <input
                type="checkbox"
                checked={planConfig.dry_sweeps}
                onChange={(e) =>
                  onUpdateConfig({ ...planConfig, preset_id: null, dry_sweeps: e.target.checked })
                }
                className="h-4 w-4 rounded accent-teal-600"
              />
              Uses dry broom (jhadu) daily
            </label>
          </div>
        </div>

        {/* Household Members Builder */}
        <div className="rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">
            Household Members ({planConfig.members.length})
          </h3>
          <form onSubmit={addMember} className="mt-2.5 flex flex-wrap gap-2">
            <label htmlFor="new-member-name" className="sr-only">
              New member name
            </label>
            <input
              id="new-member-name"
              type="text"
              value={newMemberName}
              onChange={(e) => setNewMemberName(e.target.value)}
              placeholder="Member name (e.g., Rohan)"
              className="min-w-[140px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs placeholder:text-slate-500 focus:border-teal-600 focus:outline-none"
            />
            <label htmlFor="new-member-age" className="sr-only">
              New member age
            </label>
            <input
              id="new-member-age"
              type="number"
              min={1}
              max={105}
              value={newMemberAge}
              onChange={(e) => setNewMemberAge(e.target.value)}
              className="w-16 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold"
              title="Age"
            />
            <label htmlFor="new-member-condition" className="sr-only">
              Member health sensitivity condition
            </label>
            <select
              id="new-member-condition"
              value={newMemberCond}
              onChange={(e) => setNewMemberCond(e.target.value)}
              className="rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold"
            >
              {CONDITIONS.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="inline-flex items-center gap-1 rounded-xl bg-teal-700 px-3 py-2 text-xs font-bold text-white hover:bg-teal-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <UserPlus className="h-3.5 w-3.5" aria-hidden="true" /> Add
            </button>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {planConfig.members.map((m, idx) => (
              <div
                key={`${m.name}-${idx}`}
                className="flex items-center gap-2 rounded-xl bg-white px-3 py-1.5 text-xs shadow-sm ring-1 ring-slate-200/70"
              >
                <span className="font-bold text-slate-900">
                  {m.name} ({m.age}y)
                </span>
                <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-bold text-teal-800">
                  {m.conditions.join(", ") || "adult"}
                </span>
                {planConfig.members.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeMember(idx)}
                    aria-label={`Remove ${m.name}`}
                    className="text-slate-500 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Add / Manage Tasks */}
        <div className="rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">
            Daily Commitments &amp; Routines
          </h3>
          <form onSubmit={addActivity} className="mt-2.5 flex flex-wrap gap-2">
            <label htmlFor="new-activity-name" className="sr-only">
              New daily commitment or task name
            </label>
            <input
              id="new-activity-name"
              type="text"
              value={newActName}
              onChange={(e) => setNewActName(e.target.value)}
              placeholder="e.g., Tuition drop-off or Evening walk"
              className="min-w-[150px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs placeholder:text-slate-500 focus:border-teal-600 focus:outline-none"
            />
            <label htmlFor="new-activity-member" className="sr-only">
              Assigned household member
            </label>
            <select
              id="new-activity-member"
              value={newActMember || planConfig.members[0]?.name || ""}
              onChange={(e) => setNewActMember(e.target.value)}
              className="rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold"
            >
              {planConfig.members.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            <label htmlFor="new-activity-flexibility" className="sr-only">
              Task schedule flexibility
            </label>
            <select
              id="new-activity-flexibility"
              value={newActFlex}
              onChange={(e) => setNewActFlex(e.target.value)}
              className="rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold"
            >
              <option value="flexible">Flexible</option>
              <option value="fixed">Fixed</option>
            </select>
            <label htmlFor="new-activity-hour" className="sr-only">
              Planned hour from 0 to 23
            </label>
            <input
              id="new-activity-hour"
              type="number"
              min={0}
              max={23}
              value={newActHour}
              onChange={(e) => setNewActHour(e.target.value)}
              className="w-16 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold"
              title="Planned Hour (0-23)"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Add
            </button>
          </form>

          <div className="mt-3 max-h-40 space-y-1.5 overflow-y-auto">
            {planConfig.activities.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between rounded-xl bg-white px-3 py-2 text-xs ring-1 ring-slate-200/60"
              >
                <span className="truncate font-medium text-slate-800">
                  <span
                    className={`mr-2 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
                      a.flexibility === "fixed"
                        ? "bg-amber-100 text-amber-900"
                        : "bg-emerald-100 text-emerald-900"
                    }`}
                  >
                    {a.flexibility}
                  </span>
                  {a.name} • {a.member_name} ({String(a.planned_hour).padStart(2, "0")}:00)
                </span>
                {planConfig.activities.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeActivity(a.id)}
                    aria-label={`Remove task ${a.name}`}
                    className="rounded-lg p-1 text-slate-500 hover:bg-rose-50 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
                    title="Remove task"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={onResetSaved}
          className="inline-flex items-center gap-1.5 rounded-xl bg-slate-100 px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          Reset Saved Household
        </button>

        <button
          type="button"
          onClick={onClose}
          className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-5 py-2.5 text-xs font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {saving ? "Recalculating..." : "Save & Close"}
        </button>
      </div>
    </Modal>
  );
}
