import {
  CATEGORY_TEMPLATES,
  HOUSEHOLD_STORAGE_KEY,
  LANGUAGES,
  TRANSPORT_MODES
} from "../data/constants";
import { detectPlatform } from "../utils/pwaAndPermissions";

const VALID_LANGS = new Set(LANGUAGES.map((l) => l.key));
const VALID_MODES = new Set(TRANSPORT_MODES.map((m) => m.key));
const VALID_CATEGORIES = new Set(Object.keys(CATEGORY_TEMPLATES));
const VALID_BUDGETS = new Set(["rs_0", "under_500", "under_2200"]);
const VALID_FLEX = new Set(["fixed", "flexible"]);

function isPlainObject(val) {
  return Boolean(val) && typeof val === "object" && !Array.isArray(val);
}

function sanitizeMembers(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter(
      (m) =>
        isPlainObject(m) &&
        typeof m.name === "string" &&
        m.name.trim().length > 0 &&
        Number.isFinite(Number(m.age)) &&
        Array.isArray(m.conditions)
    )
    .slice(0, 20)
    .map((m) => ({
      name: m.name.trim().slice(0, 60),
      age: Math.round(Math.max(0, Math.min(110, Number(m.age)))),
      conditions: m.conditions.filter((c) => typeof c === "string" && c.trim()).slice(0, 10)
    }));
}

function sanitizeRooms(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter((r) => isPlainObject(r) && typeof r.name === "string" && r.name.trim().length > 0)
    .slice(0, 20)
    .map((r) => ({
      name: r.name.trim().slice(0, 60),
      ext_windows: Math.round(Math.max(0, Math.min(10, Number(r.ext_windows ?? 1) || 0))),
      road_facing: Boolean(r.road_facing),
      kitchen_adjacent: Boolean(r.kitchen_adjacent),
      large_volume: Boolean(r.large_volume)
    }));
}

function sanitizeActivities(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter(
      (a) =>
        isPlainObject(a) &&
        typeof a.id === "string" &&
        a.id.trim().length > 0 &&
        typeof a.name === "string" &&
        a.name.trim().length > 0 &&
        VALID_FLEX.has(a.flexibility) &&
        Number.isInteger(Number(a.planned_hour)) &&
        Number(a.planned_hour) >= 0 &&
        Number(a.planned_hour) <= 23 &&
        Number.isFinite(Number(a.duration_min)) &&
        Number(a.duration_min) >= 5 &&
        Number(a.duration_min) <= 720 &&
        typeof a.member_name === "string" &&
        a.member_name.trim().length > 0
    )
    .slice(0, 40)
    .map((a) => ({
      ...a,
      id: a.id.trim().slice(0, 60),
      name: a.name.trim().slice(0, 100),
      planned_hour: Number(a.planned_hour),
      duration_min: Math.round(Number(a.duration_min)),
      member_name: a.member_name.trim().slice(0, 60)
    }));
}

function sanitizeCoords(rawLat, rawLon) {
  const lat = Number(rawLat);
  const lon = Number(rawLon);
  const valid =
    rawLat != null &&
    rawLon != null &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    lat >= 6.0 &&
    lat <= 37.5 &&
    lon >= 68.0 &&
    lon <= 97.5;
  return valid ? [lat, lon] : [null, null];
}

export function sanitizeSavedHousehold(raw) {
  if (!isPlainObject(raw)) return null;
  const [lat, lon] = sanitizeCoords(raw.lat, raw.lon);
  const clean = {
    city: typeof raw.city === "string" && raw.city.trim() ? raw.city.trim().slice(0, 100) : "mumbai",
    area_name: typeof raw.area_name === "string" && raw.area_name.trim() ? raw.area_name.trim().slice(0, 80) : null,
    state: typeof raw.state === "string" && raw.state.trim() ? raw.state.trim().slice(0, 80) : null,
    lat,
    lon,
    language: VALID_LANGS.has(raw.language) ? raw.language : "en"
  };
  if (VALID_CATEGORIES.has(raw.user_category)) clean.user_category = raw.user_category;
  if (VALID_BUDGETS.has(raw.budget_tier)) clean.budget_tier = raw.budget_tier;
  if (VALID_MODES.has(raw.commute_mode)) clean.commute_mode = raw.commute_mode;
  if (VALID_MODES.has(raw.target_commute_mode)) clean.target_commute_mode = raw.target_commute_mode;
  if (typeof raw.commute_km === "number" && Number.isFinite(raw.commute_km) && raw.commute_km >= 0 && raw.commute_km <= 200) {
    clean.commute_km = raw.commute_km;
  }
  if (typeof raw.uses_agarbatti_or_coils === "boolean") clean.uses_agarbatti_or_coils = raw.uses_agarbatti_or_coils;
  if (typeof raw.dry_sweeps === "boolean") clean.dry_sweeps = raw.dry_sweeps;
  const members = sanitizeMembers(raw.members);
  if (members.length > 0) clean.members = members;
  const rooms = sanitizeRooms(raw.rooms);
  if (rooms.length > 0) clean.rooms = rooms;
  const activities = sanitizeActivities(raw.activities);
  if (activities.length > 0) clean.activities = activities;
  return clean;
}

export const INITIAL_CHAT_MESSAGES = [
  {
    role: "assistant",
    text: "Ask anything about today's schedule, window timing, masks, or CO2 savings. Every answer is grounded strictly in Today's Live Data.",
    source: "system"
  }
];

export function loadSavedHousehold() {
  try {
    const raw = localStorage.getItem(HOUSEHOLD_STORAGE_KEY);
    if (!raw) return null;
    const sanitized = sanitizeSavedHousehold(JSON.parse(raw));
    if (!sanitized) {
      clearSavedHousehold();
      return null;
    }
    return sanitized;
  } catch {
    clearSavedHousehold();
    return null;
  }
}

export function saveHousehold(config) {
  try {
    if (!config) return;
    localStorage.setItem(
      HOUSEHOLD_STORAGE_KEY,
      JSON.stringify({
        city: config.city || "mumbai",
        area_name: config.area_name || null,
        state: config.state || null,
        lat: config.lat ?? null,
        lon: config.lon ?? null,
        language: config.language || "en",
        user_category: config.user_category || "adults_commuters",
        members: config.members,
        rooms: config.rooms,
        budget_tier: config.budget_tier,
        uses_agarbatti_or_coils: config.uses_agarbatti_or_coils,
        dry_sweeps: config.dry_sweeps,
        activities: config.activities,
        commute_mode: config.commute_mode,
        target_commute_mode: config.target_commute_mode,
        commute_km: config.commute_km
      })
    );
  } catch {
    // Ignore storage quota errors
  }
}

export function clearSavedHousehold() {
  try {
    localStorage.removeItem(HOUSEHOLD_STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}

export function createInitialPlanState(fallbackCities = {}) {
  return {
    citiesMap: fallbackCities,
    presets: [],
    activeCategoryId: "adults_commuters",
    activePresetId: null,
    planConfig: null,
    planResult: null,
    selectedMember: "ALL",
    simulateStale: false,
    deferredPrompt: null,
    isStandalone: detectPlatform().isStandalone,
    emergencyBannerMsg: null,
    loading: true,
    loadingText: "Fetching live air data...",
    explaining: false,
    locating: false,
    gpsError: null,
    errorMsg: null,
    chatMessages: INITIAL_CHAT_MESSAGES
  };
}

export function planReducer(state, action) {
  switch (action.type) {
    case "BOOT_LOADED":
      return {
        ...state,
        citiesMap:
          action.citiesData && Object.keys(action.citiesData).length
            ? action.citiesData
            : state.citiesMap,
        presets: Array.isArray(action.presetsList) && action.presetsList.length ? action.presetsList : state.presets,
        activeCategoryId: action.initialCategory,
        activePresetId: null,
        planConfig: action.initialConfig
      };
    case "BOOT_FAILED":
      return { ...state, errorMsg: action.errorMsg, loading: false };
    case "PLAN_START":
      return {
        ...state,
        loadingText: action.statusLabel,
        errorMsg: null,
        explaining: action.explaining ? true : state.explaining
      };
    case "PLAN_SUCCESS":
      return {
        ...state,
        planResult: action.result,
        emergencyBannerMsg: action.result.evidence_bundle?.emergency_alert
          ? action.result.evidence_bundle.emergency_message
          : state.emergencyBannerMsg
      };
    case "PLAN_ERROR":
      return { ...state, errorMsg: action.errorMsg };
    case "PLAN_FINISH":
      return { ...state, loading: false, explaining: false };
    case "SELECT_CATEGORY":
      return {
        ...state,
        activeCategoryId: action.categoryId,
        activePresetId: null,
        selectedMember: "ALL",
        planConfig: action.config,
        loading: true
      };
    case "SELECT_PRESET":
      return {
        ...state,
        activeCategoryId: action.categoryId,
        activePresetId: action.presetId,
        selectedMember: "ALL",
        planConfig: action.config,
        emergencyBannerMsg: null,
        gpsError: null,
        loading: true
      };
    case "APPLY_CONFIG":
      return {
        ...state,
        planConfig: action.config,
        activePresetId: action.clearPreset ? null : state.activePresetId,
        selectedMember: action.resetMember ? "ALL" : state.selectedMember,
        gpsError: action.clearGpsError ? null : state.gpsError,
        loading: action.loading ? true : state.loading
      };
    case "TOGGLE_STALE":
      return { ...state, simulateStale: action.simulateStale };
    case "SET_LOCATING":
      return {
        ...state,
        locating: action.locating,
        loadingText: action.loadingText ?? state.loadingText,
        gpsError: action.gpsError === undefined ? state.gpsError : action.gpsError
      };
    case "SET_INSTALL_PROMPT":
      return { ...state, deferredPrompt: action.deferredPrompt };
    case "MARK_INSTALLED":
      return { ...state, deferredPrompt: null, isStandalone: true };
    case "SET_SELECTED_MEMBER":
      return { ...state, selectedMember: action.selectedMember };
    case "SET_EMERGENCY_BANNER":
      return { ...state, emergencyBannerMsg: action.emergencyBannerMsg };
    case "SET_CHAT_MESSAGES": {
      const next =
        typeof action.value === "function" ? action.value(state.chatMessages) : action.value;
      return { ...state, chatMessages: next };
    }
    default:
      return state;
  }
}
