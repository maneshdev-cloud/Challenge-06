const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 25000;

function extractErrorMessage(rawText, status, statusText) {
  if (rawText) {
    try {
      const parsed = JSON.parse(rawText);
      if (parsed?.detail) {
        return typeof parsed.detail === "string" ? parsed.detail : `Request failed (${status}).`;
      }
    } catch {
      const clean = rawText.trim();
      if (clean) return clean;
    }
  }
  return statusText ? `Request failed (${status}: ${statusText}).` : `Request failed (${status}).`;
}

async function requestJson(path, options = {}) {
  const { signal: externalSignal, headers: customHeaders, ...restOptions } = options;
  const method = (restOptions.method || "GET").toUpperCase();
  const isSafeRetry = method === "GET" || method === "HEAD";
  const maxAttempts = isSafeRetry ? 2 : 1;
  let lastErr;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (externalSignal?.aborted) {
      const abortErr = new Error("Request cancelled.");
      abortErr.name = "AbortError";
      throw abortErr;
    }

    const controller = new AbortController();
    let timedOut = false;
    const onExternalAbort = () => controller.abort();
    externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...restOptions,
        headers: { "Content-Type": "application/json", ...(customHeaders || {}) },
        signal: controller.signal
      });

      if (res.ok) {
        return await res.json();
      }
      const detail = (await res.text()).trim();
      // Retry once only for idempotent GET/HEAD requests on empty 5xx proxy glitches
      if (attempt < maxAttempts && !detail && res.status >= 500) {
        clearTimeout(timer);
        await new Promise((r) => setTimeout(r, 350));
        continue;
      }
      throw new Error(extractErrorMessage(detail, res.status, res.statusText));
    } catch (err) {
      if (externalSignal?.aborted) {
        const abortErr = new Error("Request cancelled.");
        abortErr.name = "AbortError";
        throw abortErr;
      }
      lastErr = err;
      if (attempt < maxAttempts && (err?.name === "TypeError" || timedOut)) {
        clearTimeout(timer);
        await new Promise((r) => setTimeout(r, 350));
        continue;
      }
      if (timedOut || err?.name === "AbortError") {
        throw new Error("Request timed out; please retry.");
      }
      throw err;
    } finally {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", onExternalAbort);
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

export function fetchAirSnapshot(city, simulateStale = false, coords = null, options = {}) {
  const params = { city, simulate_stale: String(simulateStale) };
  if (coords?.lat != null && coords?.lon != null) {
    params.lat = String(coords.lat);
    params.lon = String(coords.lon);
  }
  if (coords?.area_name) {
    params.area_name = coords.area_name;
  }
  const q = new URLSearchParams(params);
  return requestJson(`/v1/air?${q.toString()}`, options);
}

export function generatePlan(planRequest, options = {}) {
  return requestJson("/v1/plan", {
    method: "POST",
    body: JSON.stringify(planRequest),
    ...options
  });
}

export function sendChatQuestion(
  message,
  evidenceBundle,
  language,
  evidenceSignature = "",
  options = {}
) {
  return requestJson("/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      evidence_bundle: evidenceBundle,
      evidence_signature: evidenceSignature || "",
      language
    }),
    ...options
  });
}

export async function auditRoomPhoto(file, { city, language, area_name, current_naqi }) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("city", city || "delhi");
  formData.append("language", language || "en");
  if (area_name) formData.append("area_name", area_name);
  if (current_naqi != null) formData.append("current_naqi", String(current_naqi));

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}/v1/audit-room`, {
      method: "POST",
      body: formData,
      signal: controller.signal
    });
    const rawText = await res.text();
    if (!res.ok) {
      let message = `Audit failed (${res.status})`;
      if (rawText) {
        try {
          const parsed = JSON.parse(rawText);
          if (parsed?.detail) message = parsed.detail;
        } catch {
          message = rawText.trim();
        }
      }
      throw new Error(message);
    }
    return rawText ? JSON.parse(rawText) : {};
  } catch (err) {
    if (timedOut || err?.name === "AbortError") {
      throw new Error("Photo audit timed out; please try a smaller photo or retry.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
