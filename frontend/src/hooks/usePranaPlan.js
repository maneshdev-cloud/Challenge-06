import { useCallback, useEffect, useRef, useState } from "react";
import { fetchCities, fetchPresets, generatePlan, reverseGeocode } from "../api/client";
import {
  CATEGORY_LABELS,
  CATEGORY_TEMPLATES,
  FALLBACK_CITIES,
  HOUSEHOLD_STORAGE_KEY,
  LANGUAGES,
  PRESET_TO_CATEGORY
} from "../data/constants";
import { detectPlatform } from "../utils/pwaAndPermissions";

const SLIDER_DEBOUNCE_MS = 220;

const INITIAL_CHAT_MESSAGES = [
  {
    role: "assistant",
    text: "Ask anything about today's schedule, window timing, masks, or CO2 savings. Every answer is grounded strictly in Today's Live Data.",
    source: "system"
  }
];

function loadSavedHousehold() {
  try {
    const raw = localStorage.getItem(HOUSEHOLD_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveHousehold(config) {
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

export default function usePranaPlan() {
  const [citiesMap, setCitiesMap] = useState(FALLBACK_CITIES);
  const [presets, setPresets] = useState([]);
  const [activeCategoryId, setActiveCategoryId] = useState("adults_commuters");
  const [activePresetId, setActivePresetId] = useState(null);
  const [planConfig, setPlanConfig] = useState(null);
  const [planResult, setPlanResult] = useState(null);
  const [selectedMember, setSelectedMember] = useState("ALL");
  const [simulateStale, setSimulateStale] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isStandalone, setIsStandalone] = useState(() => detectPlatform().isStandalone);
  const [emergencyBannerMsg, setEmergencyBannerMsg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingText, setLoadingText] = useState("Fetching live air data...");
  const [explaining, setExplaining] = useState(false);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [chatMessages, setChatMessages] = useState(INITIAL_CHAT_MESSAGES);

  const planAbortRef = useRef(null);
  const debounceTimerRef = useRef(null);
  const requestSeqRef = useRef(0);

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

      setLoadingText(statusLabel);
      setErrorMsg(null);
      if (!skipLlm) {
        setExplaining(true);
      }

      try {
        const res = await generatePlan(
          {
            ...config,
            simulate_stale: staleFlag,
            skip_llm: skipLlm
          },
          { signal: controller.signal }
        );
        if (seq !== requestSeqRef.current) return;
        setPlanResult(res);
        if (res.evidence_bundle?.emergency_alert) {
          setEmergencyBannerMsg(res.evidence_bundle.emergency_message);
        }
      } catch (err) {
        if (err?.name === "AbortError" || seq !== requestSeqRef.current) return;
        setErrorMsg(err.message);
      } finally {
        if (seq === requestSeqRef.current) {
          setLoading(false);
          setExplaining(false);
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
    const langCode = planConfig?.language || "en";
    const meta = LANGUAGES.find((l) => l.key === langCode);
    document.documentElement.lang = meta?.htmlLang || "en";
  }, [planConfig?.language]);

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (planAbortRef.current) planAbortRef.current.abort();
    };
  }, []);

  useEffect(() => {
    function handleBeforeInstall(e) {
      e.preventDefault();
      setDeferredPrompt(e);
    }
    function handleAppInstalled() {
      setDeferredPrompt(null);
      setIsStandalone(true);
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
      .then(([list, citiesData]) => {
        if (!mounted) return;
        if (citiesData && Object.keys(citiesData).length) {
          setCitiesMap(citiesData);
        }
        if (Array.isArray(list) && list.length) {
          setPresets(list);
        }
        const saved = loadSavedHousehold();
        const initialCat = saved?.user_category || "adults_commuters";
        const baseTemplate = CATEGORY_TEMPLATES[initialCat] || CATEGORY_TEMPLATES.adults_commuters;
        const initialConfig = {
          ...baseTemplate,
          ...(saved || {}),
          user_category: initialCat,
          city: saved?.city || "mumbai",
          language: saved?.language || "en",
          preset_id: null,
          area_name: saved?.area_name || null,
          state: saved?.state || null,
          lat: saved?.lat ?? null,
          lon: saved?.lon ?? null,
          walk_override_hour: null
        };
        setActiveCategoryId(initialCat);
        setActivePresetId(null);
        setPlanConfig(initialConfig);
        runPlan(initialConfig, false, false, "Fetching live air data...");
      })
      .catch((err) => {
        if (mounted) {
          setErrorMsg(`Backend connection failed: ${err.message}`);
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, [runPlan]);

  async function handleTriggerNativeInstall() {
    if (!deferredPrompt) return "unavailable";
    deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    if (choice?.outcome === "accepted") {
      setDeferredPrompt(null);
    }
    return choice?.outcome || "dismissed";
  }

  function handleSelectCategory(catId) {
    if (!planConfig) return;
    const tpl = CATEGORY_TEMPLATES[catId];
    if (!tpl) return;
    const nextConfig = {
      ...planConfig,
      ...tpl,
      user_category: catId,
      preset_id: null,
      walk_override_hour: null
    };
    setActiveCategoryId(catId);
    setActivePresetId(null);
    setSelectedMember("ALL");
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    setLoading(true);
    runPlan(
      nextConfig,
      simulateStale,
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
    setActiveCategoryId(mappedCat);
    setActivePresetId(preset.id);
    setSelectedMember("ALL");
    setPlanConfig(nextConfig);
    setEmergencyBannerMsg(null);
    setGpsError(null);
    setLoading(true);
    runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
  }

  function updateLocationAndRun(patch, clearPreset = true) {
    if (!planConfig) return;
    const nextConfig = {
      ...planConfig,
      ...patch,
      ...(clearPreset ? { walk_override_hour: null, preset_id: null } : {})
    };
    if (clearPreset) setActivePresetId(null);
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    setGpsError(null);
    setLoading(true);
    runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
  }

  function handleCityChange(newCity) {
    updateLocationAndRun({ city: newCity, area_name: null, state: null, lat: null, lon: null });
  }

  function handleAreaChange(selectedArea) {
    if (!planConfig) return;
    if (selectedArea === "__center__") {
      updateLocationAndRun({ area_name: null, state: null, lat: null, lon: null }, false);
      return;
    }
    const areas = citiesMap[planConfig.city]?.areas || [];
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
    if (!planConfig) return;
    if (!navigator.geolocation) {
      setGpsError("Geolocation is unavailable in this browser; please search your city above.");
      return;
    }
    setLocating(true);
    setLoadingText("Detecting your area...");
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(4));
        const lon = Number(pos.coords.longitude.toFixed(4));
        try {
          const rev = await reverseGeocode(lat, lon);
          setLocating(false);
          updateLocationAndRun({
            city: rev.city,
            area_name: rev.area_name,
            state: rev.state || null,
            lat,
            lon
          });
        } catch (err) {
          setLocating(false);
          setGpsError(`Could not resolve area name (${err.message}). Search your city manually.`);
        }
      },
      (err) => {
        setLocating(false);
        setGpsError(`Location unavailable (${err.message}). Search your city above instead.`);
      },
      { enableHighAccuracy: false, timeout: 8000 }
    );
  }

  function handleLanguageChange(newLang) {
    if (!planConfig) return;
    const nextConfig = { ...planConfig, language: newLang };
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    runPlan(nextConfig, simulateStale, false, "Recalculating plan...");
  }

  function handleToggleStale() {
    const nextStale = !simulateStale;
    setSimulateStale(nextStale);
    if (planConfig) {
      runPlan(planConfig, nextStale, true, "Recalculating plan...");
    }
  }

  function handleWalkHourChange(hour) {
    if (!planConfig) return;
    const nextConfig = { ...planConfig, walk_override_hour: hour };
    setPlanConfig(nextConfig);
    scheduleDebouncedPlan(nextConfig, simulateStale);
  }

  function handleResetWalkHour() {
    if (!planConfig) return;
    const nextConfig = { ...planConfig, walk_override_hour: null };
    setPlanConfig(nextConfig);
    runPlan(nextConfig, simulateStale, true, "Recalculating plan...");
  }

  function handleTargetCommuteChange(mode) {
    if (!planConfig) return;
    const nextConfig = { ...planConfig, target_commute_mode: mode };
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    runPlan(nextConfig, simulateStale, true, "Recalculating plan...");
  }

  function handleCommuteKmChange(km) {
    if (!planConfig) return;
    const nextConfig = { ...planConfig, commute_km: km };
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    scheduleDebouncedPlan(nextConfig, simulateStale);
  }

  function handleUpdateCustomConfig(nextConfig) {
    setActivePresetId(null);
    setSelectedMember("ALL");
    setPlanConfig(nextConfig);
    saveHousehold(nextConfig);
    runPlan(nextConfig, simulateStale, true, "Recalculating plan...");
  }

  function handleResetSavedHousehold() {
    try {
      localStorage.removeItem(HOUSEHOLD_STORAGE_KEY);
    } catch {
      // ignore storage errors
    }
    handleSelectCategory("adults_commuters");
  }

  return {
    citiesMap,
    presets,
    activeCategoryId,
    activePresetId,
    planConfig,
    planResult,
    selectedMember,
    setSelectedMember,
    simulateStale,
    deferredPrompt,
    isStandalone,
    emergencyBannerMsg,
    setEmergencyBannerMsg,
    loading,
    loadingText,
    explaining,
    locating,
    gpsError,
    errorMsg,
    chatMessages,
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
