export function computeCommunityImpact(bundle, householdsCount = 50) {
  const safeHomes = Math.max(1, Math.min(5000, Math.round(Number(householdsCount) || 50)));
  const dailyDoseSavedUg = Number(bundle?.breathe_less?.dose_avoided_ug || 0) * safeHomes;
  const dailyCo2SavedKg = Number(bundle?.emit_less?.co2_saved_kg || 0) * safeHomes;
  const dailyTailpipePm25Mg = Number(bundle?.emit_less?.tailpipe_pm25_saved_mg || 0) * safeHomes;
  const monthlyCo2SavedKg = dailyCo2SavedKg * 30;
  return {
    householdsCount: safeHomes,
    dailyDoseSavedMg: Number((dailyDoseSavedUg / 1000).toFixed(2)),
    dailyCo2SavedKg: Number(dailyCo2SavedKg.toFixed(1)),
    monthlyCo2SavedKg: Number(monthlyCo2SavedKg.toFixed(0)),
    dailyTailpipePm25G: Number((dailyTailpipePm25Mg / 1000).toFixed(2))
  };
}

function escapeIcsText(text) {
  return String(text || "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

function getIstDateDigits(nowDate = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(nowDate);
  const year = parts.find((p) => p.type === "year")?.value || "2026";
  const month = parts.find((p) => p.type === "month")?.value || "01";
  const day = parts.find((p) => p.type === "day")?.value || "01";
  return `${year}${month}${day}`;
}

export function generateCleanWindowIcs(bundle, nowDate = new Date()) {
  const air = bundle?.air_snapshot;
  if (!air?.golden_window) return "";
  const gw = air.golden_window;
  const startHour = Math.max(0, Math.min(22, Number(gw.start_hour ?? 13)));
  const endHour = Math.max(startHour + 1, Math.min(23, Number(gw.end_hour ?? startHour + 2)));
  const ymd = getIstDateDigits(nowDate);
  const dtStart = `${ymd}T${String(startHour).padStart(2, "0")}0000`;
  const dtEnd = `${ymd}T${String(endHour).padStart(2, "0")}0000`;
  const dtStamp = nowDate.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const loc =
    air.area_name && air.area_name.toLowerCase() !== air.city_name.toLowerCase()
      ? `${air.area_name}, ${air.city_name}`
      : air.city_name;
  const summary = gw.is_clean_air_day
    ? `PRANA-AI Clean-Air Window (${loc} • NAQI ${gw.mean_naqi})`
    : gw.has_meaningful_window
      ? `PRANA-AI Lowest-Smog Outdoor Window (${loc} • ${gw.mean_pm25} ug/m3)`
      : `PRANA-AI Indoor Recovery Reminder (${loc} • ${gw.mean_pm25} ug/m3)`;
  const description = `${gw.advisory} (Modeled estimate via Open-Meteo + PRANA-AI)`;

  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//PRANA-AI//Clean Air Planner//EN",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:prana-window-${ymd}-${air.city}@prana-ai`,
    `DTSTAMP:${dtStamp}`,
    `DTSTART;TZID=Asia/Kolkata:${dtStart}`,
    `DTEND;TZID=Asia/Kolkata:${dtEnd}`,
    `SUMMARY:${escapeIcsText(summary)}`,
    `LOCATION:${escapeIcsText(loc)}`,
    `DESCRIPTION:${escapeIcsText(description)}`,
    "END:VEVENT",
    "END:VCALENDAR",
    ""
  ].join("\r\n");
}
