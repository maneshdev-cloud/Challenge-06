const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/+$/, "");

async function requestJson(path, options = {}) {
  const maxAttempts = 2;
  let lastErr;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        signal: controller.signal,
        ...options
      });
      clearTimeout(timer);
      if (res.ok) {
        return res.json();
      }
      const detail = (await res.text()).trim();
      // Retry once briefly if Vite proxy returns an empty 500/502/503 during hot reload
      if (attempt < maxAttempts && !detail && res.status >= 500) {
        await new Promise((r) => setTimeout(r, 350));
        continue;
      }
      throw new Error(`API ${res.status}: ${detail || res.statusText || "Server busy"}`);
    } catch (err) {
      clearTimeout(timer);
      lastErr = err;
      if (attempt < maxAttempts && (err?.name === "TypeError" || err?.name === "AbortError")) {
        await new Promise((r) => setTimeout(r, 350));
        continue;
      }
      throw err?.name === "AbortError" ? new Error("Request timed out; please retry.") : err;
    }
  }
  throw lastErr;
}

export function fetchPresets() {
  return requestJson("/v1/presets");
}

export function fetchCities() {
  return requestJson("/v1/cities");
}

export function searchIndianLocations(query, count = 5) {
  const q = new URLSearchParams({ q: query.trim(), count: String(count) });
  return requestJson(`/v1/geocode?${q.toString()}`);
}

export function reverseGeocode(lat, lon) {
  const q = new URLSearchParams({ lat: String(lat), lon: String(lon) });
  return requestJson(`/v1/reverse-geocode?${q.toString()}`);
}

export function fetchAirSnapshot(city, simulateStale = false, coords = null) {
  const params = { city, simulate_stale: String(simulateStale) };
  if (coords?.lat != null && coords?.lon != null) {
    params.lat = String(coords.lat);
    params.lon = String(coords.lon);
  }
  if (coords?.area_name) {
    params.area_name = coords.area_name;
  }
  const q = new URLSearchParams(params);
  return requestJson(`/v1/air?${q.toString()}`);
}

export function generatePlan(planRequest) {
  return requestJson("/v1/plan", {
    method: "POST",
    body: JSON.stringify(planRequest)
  });
}

export function sendChatQuestion(message, evidenceBundle, language) {
  return requestJson("/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      evidence_bundle: evidenceBundle,
      language
    })
  });
}

export async function auditRoomPhoto(file, { city, language, area_name, current_naqi }) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("city", city || "delhi");
  formData.append("language", language || "en");
  if (area_name) formData.append("area_name", area_name);
  if (current_naqi != null) formData.append("current_naqi", String(current_naqi));

  const res = await fetch(`${API_BASE}/v1/audit-room`, {
    method: "POST",
    body: formData
  });
  if (!res.ok) {
    let message = `Audit failed (${res.status})`;
    try {
      const json = await res.json();
      if (json?.detail) message = json.detail;
    } catch {
      const text = await res.text();
      if (text) message = text;
    }
    throw new Error(message);
  }
  return res.json();
}
