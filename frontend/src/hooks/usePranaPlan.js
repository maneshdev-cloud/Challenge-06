import { useCallback, useEffect, useReducer, useRef } from "react";
import { fetchCities, fetchPresets, generatePlan, reverseGeocode } from "../api/client";
import {
  CATEGORY_LABELS,
  CATEGORY_TEMPLATES,
  FALLBACK_CITIES,
  LANGUAGES,
  PRESET_TO_CATEGORY
} from "../data/constants";
import {
  clearSavedHousehold,
  createInitialPlanState,
  loadSavedHousehold,
  planReducer,
  saveHousehold
} from "./planReducer";

const SLIDER_DEBOUNCE_MS = 220;

export default function usePranaPlan() {
  const [state, dispatch] = useReducer(planReducer, FALLBACK_CITIES, createInitialPlanState);

  const planAbortRef = useRef(null);
  const debounceTimerRef = useRef(null);
  const requestSeqRef = useRef(0);

  const setSelectedMember = useCallback(
    (selectedMember) => dispatch({ type: "SET_SELECTED_MEMBER", selectedMember }),
    []
  );
  const setEmergencyBannerMsg = useCallback(
    (emergencyBannerMsg) => dispatch({ type: "SET_EMERGENCY_BANNER", emergencyBannerMsg }),
    []
  );
  const setChatMessages = useCallback(
    (value) => dispatch({ type: "SET_CHAT_MESSAGES", value }),
    []
  );

  const runPlan = useCallback(
    async (config, staleFlag, skipLlm = false, statusLabel = "Recalculating plan...") => {
      if (!config) return;
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      if (planAbortRef.current) {
        planAbortRef.current.abort();
      }
      const controller = new AbortController();
      planAbortRef.current = controller;
      requestSeqRef.current += 1;
      const seq = requestSeqRef.current;

      dispatch({ type: "PLAN_START", statusLabel, explaining: !skipLlm });
      try {
        const result = await generatePlan(
          { ...config, simulate_stale: staleFlag, skip_llm: skipLlm },
          { signal: controller.signal }
        );
        if (seq !== requestSeqRef.current) return;
        dispatch({ type: "PLAN_SUCCESS", result });
      } catch (err) {
        if (err?.name === "AbortError" || seq !== requestSeqRef.current) return;
        dispatch({ type: "PLAN_ERROR", errorMsg: err.message });
      } finally {
        if (seq === requestSeqRef.current) {
          dispatch({ type: "PLAN_FINISH" });
        }
      }
    },
    []
  );

  const scheduleDebouncedPlan = useCallback(
    (config, staleFlag) => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      requestSeqRef.current += 1;
      debounceTimerRef.current = setTimeout(() => {
        debounceTimerRef.current = null;
        runPlan(config, staleFlag, true, "Recalculating plan...");
      }, SLIDER_DEBOUNCE_MS);
    },
    [runPlan]
  );

  useEffect(() => {
    const langCode = state.planConfig?.language || "en";
    const meta = LANGUAGES.find((l) => l.key === langCode);
    document.documentElement.lang = meta?.htmlLang || "en";
  }, [state.planConfig?.language]);

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (planAbortRef.current) planAbortRef.current.abort();
    };
  }, []);

  useEffect(() => {
    function handleBeforeInstall(e) {
      e.preventDefault();
      dispatch({ type: "SET_INSTALL_PROMPT", deferredPrompt: e });
    }
    function handleAppInstalled() {
      dispatch({ type: "MARK_INSTALLED" });
    }
    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    window.addEventListener("appinstalled", handleAppInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
      window.removeEventListener("appinstalled", handleAppInstalled);
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.all([fetchPresets(), fetchCities().catch(() => FALLBACK_CITIES)])
      .then(([presetsList, citiesData]) => {
        if (!mounted) return;
        const saved = loadSavedHousehold();
        const initialCategory = saved?.user_category || "adults_commuters";
        const baseTemplate =
          CATEGORY_TEMPLATES[initialCategory] || CATEGORY_TEMPLATES.adults_commuters;
        const initialConfig = {
          ...baseTemplate,
          ...(saved || {}),
          user_category: initialCategory,
          city: saved?.city || "mumbai",
          language: saved?.language || "en",
          preset_id: null,
          area_name: saved?.area_name || null,
          state: saved?.state || null,
          lat: saved?.lat ?? null,
          lon: saved?.lon ?? null,
          walk_override_hour: null
        };
        dispatch({
          type: "BOOT_LOADED",
          presetsList,
          citiesData,
          initialCategory,
          initialConfig
        });
        runPlan(initialConfig, false, false, "Fetching live air data...");
      })
      .catch((err) => {
        if (mounted) {
          dispatch({ type: "BOOT_FAILED", errorMsg: `Backend connection failed: ${err.message}` });
        }
      });
    return () => {
      mounted = false;
    };
  }, [runPlan]);

  async function handleTriggerNativeInstall() {
    if (!state.deferredPrompt) return "unavailable";
    state.deferredPrompt.prompt();
    const choice = await state.deferredPrompt.userChoice;
    if (choice?.outcome === "accepted") {
      dispatch({ type: "SET_INSTALL_PROMPT", deferredPrompt: null });
    }
    return choice?.outcome || "dismissed";
  }

  function handleSelectCategory(catId) {
    if (!state.planConfig) return;
    const tpl = CATEGORY_TEMPLATES[catId];
    if (!tpl) return;
    const nextConfig = {
      ...state.planConfig,
      ...tpl,
      user_category: catId,
      preset_id: null,
      walk_override_hour: null
    };
    dispatch({ type: "SELECT_CATEGORY", categoryId: catId, config: nextConfig });
    saveHousehold(nextConfig);
    runPlan(
      nextConfig,
      state.simulateStale,
      false,
      `Updating plan for ${CATEGORY_LABELS[catId] || "Household"}...`
    );
  }

  function handleSelectPreset(preset) {
    const mappedCat = PRESET_TO_CATEGORY[preset.id] || "adults_commuters";
    const nextConfig = {
      ...preset,
      user_category: mappedCat,
      language: "en",
      preset_id: preset.id,
      area_name: null,
      state: null,
      lat: null,
      lon: null,
      walk_override_hour: null
    };
    dispatch({
      type: "SELECT_PRESET",
      categoryId: mappedCat,
      presetId: preset.id,
      config: nextConfig
    });
    runPlan(nextConfig, state.simulateStale, false, "Fetching live air data...");
  }

  function updateLocationAndRun(patch, clearPreset = true) {
    if (!state.planConfig) return;
    const nextConfig = {
      ...state.planConfig,
      ...patch,
      ...(clearPreset ? { walk_override_hour: null, preset_id: null } : {})
    };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig, clearPreset, clearGpsError: true, loading: true });
    saveHousehold(nextConfig);
    runPlan(nextConfig, state.simulateStale, false, "Fetching live air data...");
  }

  function handleCityChange(newCity) {
    updateLocationAndRun({ city: newCity, area_name: null, state: null, lat: null, lon: null });
  }

  function handleAreaChange(selectedArea) {
    if (!state.planConfig) return;
    if (selectedArea === "__center__") {
      updateLocationAndRun({ area_name: null, state: null, lat: null, lon: null }, false);
      return;
    }
    const areas = state.citiesMap[state.planConfig.city]?.areas || [];
    const match = areas.find((a) => a.name === selectedArea);
    if (!match) return;
    updateLocationAndRun(
      { area_name: match.name, state: null, lat: match.lat, lon: match.lon },
      false
    );
  }

  function handleSelectGeocode(item) {
    if (!item) return;
    updateLocationAndRun({
      city: item.name,
      area_name: item.name,
      state: item.state || null,
      lat: item.lat,
      lon: item.lon
    });
  }

  function handleUseMyLocation() {
    if (!state.planConfig) return;
    if (!navigator.geolocation) {
      dispatch({
        type: "SET_LOCATING",
        locating: false,
        gpsError: "Geolocation is unavailable in this browser; please search your city above."
      });
      return;
    }
    dispatch({
      type: "SET_LOCATING",
      locating: true,
      loadingText: "Detecting your area...",
      gpsError: null
    });
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(4));
        const lon = Number(pos.coords.longitude.toFixed(4));
        try {
          const rev = await reverseGeocode(lat, lon);
          dispatch({ type: "SET_LOCATING", locating: false });
          updateLocationAndRun({
            city: rev.city,
            area_name: rev.area_name,
            state: rev.state || null,
            lat,
            lon
          });
        } catch (err) {
          dispatch({
            type: "SET_LOCATING",
            locating: false,
            gpsError: `Could not resolve area name (${err.message}). Search your city manually.`
          });
        }
      },
      (err) => {
        dispatch({
          type: "SET_LOCATING",
          locating: false,
          gpsError: `Location unavailable (${err.message}). Search your city above instead.`
        });
      },
      { enableHighAccuracy: false, timeout: 8000 }
    );
  }

  function handleLanguageChange(newLang) {
    if (!state.planConfig) return;
    const nextConfig = { ...state.planConfig, language: newLang };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig });
    saveHousehold(nextConfig);
    runPlan(nextConfig, state.simulateStale, false, "Recalculating plan...");
  }

  function handleToggleStale() {
    const nextStale = !state.simulateStale;
    dispatch({ type: "TOGGLE_STALE", simulateStale: nextStale });
    if (state.planConfig) {
      runPlan(state.planConfig, nextStale, true, "Recalculating plan...");
    }
  }

  function handleWalkHourChange(hour) {
    if (!state.planConfig) return;
    const nextConfig = { ...state.planConfig, walk_override_hour: hour };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig });
    scheduleDebouncedPlan(nextConfig, state.simulateStale);
  }

  function handleResetWalkHour() {
    if (!state.planConfig) return;
    const nextConfig = { ...state.planConfig, walk_override_hour: null };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig });
    runPlan(nextConfig, state.simulateStale, true, "Recalculating plan...");
  }

  function handleTargetCommuteChange(mode) {
    if (!state.planConfig) return;
    const nextConfig = { ...state.planConfig, target_commute_mode: mode };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig });
    saveHousehold(nextConfig);
    runPlan(nextConfig, state.simulateStale, true, "Recalculating plan...");
  }

  function handleCommuteKmChange(km) {
    if (!state.planConfig) return;
    const nextConfig = { ...state.planConfig, commute_km: km };
    dispatch({ type: "APPLY_CONFIG", config: nextConfig });
    saveHousehold(nextConfig);
    scheduleDebouncedPlan(nextConfig, state.simulateStale);
  }

  function handleUpdateCustomConfig(nextConfig) {
    dispatch({ type: "APPLY_CONFIG", config: nextConfig, clearPreset: true, resetMember: true });
    saveHousehold(nextConfig);
    runPlan(nextConfig, state.simulateStale, true, "Recalculating plan...");
  }

  function handleResetSavedHousehold() {
    clearSavedHousehold();
    handleSelectCategory("adults_commuters");
  }

  return {
    ...state,
    setSelectedMember,
    setEmergencyBannerMsg,
    setChatMessages,
    runPlan,
    handleTriggerNativeInstall,
    handleSelectCategory,
    handleSelectPreset,
    handleCityChange,
    handleAreaChange,
    handleSelectGeocode,
    handleUseMyLocation,
    handleLanguageChange,
    handleToggleStale,
    handleWalkHourChange,
    handleResetWalkHour,
    handleTargetCommuteChange,
    handleCommuteKmChange,
    handleUpdateCustomConfig,
    handleResetSavedHousehold
  };
}
