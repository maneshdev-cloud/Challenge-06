export function formatHour(hour) {
  if (hour === null || hour === undefined) return "--:--";
  const h = ((Number(hour) % 24) + 24) % 24;
  return `${String(h).padStart(2, "0")}:00`;
}

export function formatHourAmPm(hour) {
  if (hour === null || hour === undefined) return "--";
  const h = ((Number(hour) % 24) + 24) % 24;
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:00 ${suffix}`;
}

export function getNaqiStyle(category) {
  switch (category) {
    case "Good":
      return { bg: "bg-emerald-100", text: "text-emerald-800", border: "border-emerald-300", dot: "bg-emerald-500" };
    case "Satisfactory":
      return { bg: "bg-lime-100", text: "text-lime-800", border: "border-lime-300", dot: "bg-lime-500" };
    case "Moderate":
      return { bg: "bg-amber-100", text: "text-amber-800", border: "border-amber-300", dot: "bg-amber-500" };
    case "Poor":
      return { bg: "bg-orange-100", text: "text-orange-800", border: "border-orange-300", dot: "bg-orange-500" };
    case "Very Poor":
      return { bg: "bg-rose-100", text: "text-rose-800", border: "border-rose-300", dot: "bg-rose-600" };
    case "Severe":
    default:
      return { bg: "bg-red-950/10", text: "text-red-900", border: "border-red-400", dot: "bg-red-700" };
  }
}

export function formatTimeIst(isoString) {
  if (!isoString) return "";
  try {
    const dt = new Date(isoString);
    return dt.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Kolkata"
    });
  } catch {
    return isoString;
  }
}

export async function copyToClipboard(text) {
  if (!text) return false;
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }
  return false;
}
