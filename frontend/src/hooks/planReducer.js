import { HOUSEHOLD_STORAGE_KEY } from "../data/constants";
import { detectPlatform } from "../utils/pwaAndPermissions";

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
    return raw ? JSON.parse(raw) : null;
  } catch {
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
