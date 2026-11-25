import React, { useCallback, useEffect, useState } from "react";
import { CalendarClock, FileText, Home, Loader2, MessageSquare, Sliders } from "lucide-react";
import { fetchCities, fetchPresets, generatePlan, reverseGeocode, sendChatQuestion } from "./api/client";
import AppInstallPermissionsModal from "./components/AppInstallPermissionsModal";
import CleanAirNoteModal from "./components/CleanAirNoteModal";
import DataFooter from "./components/DataFooter";
import DualImpactLedgers from "./components/DualImpactLedgers";
import EmergencyBanner from "./components/EmergencyBanner";
import FiveDayOutlookCard from "./components/FiveDayOutlookCard";
import GeminiChatDrawer from "./components/GeminiChatDrawer";
import HeaderBar from "./components/HeaderBar";
import HeroAirCard from "./components/HeroAirCard";
import HouseholdCustomizer from "./components/HouseholdCustomizer";
import IndoorSanctuaryCard from "./components/IndoorSanctuaryCard";
import PersonaBar from "./components/PersonaBar";
import RoutineTimeline from "./components/RoutineTimeline";
import ShowMathModal from "./components/ShowMathModal";
import SmogChartCard from "./components/SmogChartCard";
import { detectPlatform } from "./utils/pwaAndPermissions";

const STORAGE_KEY = "prana_ai_household_v1";

const FALLBACK_CITIES = {
  mumbai: {
    name: "Mumbai",
    lat: 19.076,
    lon: 72.8777,
    local_language: "mr",
    areas: [
      { name: "Andheri", lat: 19.1136, lon: 72.8697 },
      { name: "Malad West", lat: 19.1874, lon: 72.8484 },
      { name: "Bandra", lat: 19.0596, lon: 72.8295 },
      { name: "Dadar", lat: 19.0178, lon: 72.8478 },
      { name: "Navi Mumbai", lat: 19.033, lon: 73.0297 }
    ]
  },
  pune: {
    name: "Pune",
    lat: 18.5204,
    lon: 73.8567,
    local_language: "mr",
    areas: [
      { name: "Kothrud", lat: 18.5074, lon: 73.8077 },
      { name: "Hinjewadi", lat: 18.5913, lon: 73.7389 },
      { name: "Shivajinagar", lat: 18.5308, lon: 73.8475 },
      { name: "Baner", lat: 18.559, lon: 73.7868 },
      { name: "Hadapsar", lat: 18.5089, lon: 73.9259 }
    ]
  },
  delhi: {
    name: "Delhi",
    lat: 28.6139,
    lon: 77.209,
    local_language: "hi",
    areas: [
      { name: "Dwarka", lat: 28.5921, lon: 77.046 },
      { name: "Anand Vihar", lat: 28.6469, lon: 77.3164 },
      { name: "Rohini", lat: 28.7495, lon: 77.0565 },
      { name: "Saket", lat: 28.5246, lon: 77.2066 },
      { name: "Connaught Place", lat: 28.6315, lon: 77.2167 }
    ]
  },
  bengaluru: {
    name: "Bangalore",
    lat: 12.9716,
    lon: 77.5946,
    local_language: "kn",
    areas: [
      { name: "Koramangala", lat: 12.9352, lon: 77.6245 },
      { name: "Whitefield", lat: 12.9698, lon: 77.75 },
      { name: "Indiranagar", lat: 12.9784, lon: 77.6408 },
      { name: "Hebbal", lat: 13.0354, lon: 77.5988 }
    ]
  },
  kolkata: {
    name: "Kolkata",
    lat: 22.5726,
    lon: 88.3639,
    local_language: "bn",
    areas: [
      { name: "Salt Lake", lat: 22.5867, lon: 88.4171 },
      { name: "Park Street", lat: 22.5529, lon: 88.3532 },
      { name: "Ballygunge", lat: 22.528, lon: 88.3659 },
      { name: "Howrah", lat: 22.5958, lon: 88.2636 }
    ]
  }
};

const CATEGORY_LABELS = {
  students_kids: "Students & Kids",
  adults_commuters: "Adults & Commuters",
  seniors: "Seniors",
  delivery_riders: "Delivery Riders"
};

const CATEGORY_TEMPLATES = {
  students_kids: {
    user_category: "students_kids",
    budget_tier: "rs_0",
    commute_mode: "auto_cng",
    target_commute_mode: "electric_metro",
    commute_km: 12.0,
    uses_agarbatti_or_coils: false,
    dry_sweeps: true,
    members: [
      { name: "Student", age: 18, conditions: ["adult"] },
      { name: "School Child", age: 9, conditions: ["child"] }
    ],
    rooms: [
      { name: "Road-Side Living / Study Room", ext_windows: 2, road_facing: true, kitchen_adjacent: false, large_volume: false },
      { name: "Inner Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "campus_commute", name: "School / College Commute (12 km)", flexibility: "fixed", planned_hour: 8, duration_min: 45, activity_level: "seated", member_name: "Student", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "sports_play", name: "Outdoor Sports / Park Play", flexibility: "flexible", planned_hour: 17, duration_min: 45, activity_level: "child_play", member_name: "School Child", current_mask: "none", is_commute: false, is_work_shift: false },
      { id: "evening_jog", name: "Campus Run / Walk", flexibility: "flexible", planned_hour: 19, duration_min: 35, activity_level: "running_or_outdoor_work", member_name: "Student", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  adults_commuters: {
    user_category: "adults_commuters",
    budget_tier: "under_2200",
    commute_mode: "car_petrol_solo",
    target_commute_mode: "electric_metro",
    commute_km: 16.0,
    uses_agarbatti_or_coils: false,
    dry_sweeps: true,
    members: [{ name: "Commuter", age: 34, conditions: ["adult"] }],
    rooms: [
      { name: "Front Living Room", ext_windows: 2, road_facing: true, kitchen_adjacent: true, large_volume: true },
      { name: "Inner Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "office_commute", name: "Office Commute (16 km)", flexibility: "fixed", planned_hour: 9, duration_min: 60, activity_level: "seated", member_name: "Commuter", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "brisk_walk", name: "Daily Brisk Walk", flexibility: "flexible", planned_hour: 7, duration_min: 40, activity_level: "brisk_walk", member_name: "Commuter", current_mask: "none", is_commute: false, is_work_shift: false },
      { id: "errand_walk", name: "Evening Grocery Trip", flexibility: "flexible", planned_hour: 19, duration_min: 30, activity_level: "light_walk", member_name: "Commuter", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  seniors: {
    user_category: "seniors",
    budget_tier: "under_500",
    commute_mode: "auto_cng",
    target_commute_mode: "city_bus",
    commute_km: 6.0,
    uses_agarbatti_or_coils: true,
    dry_sweeps: true,
    members: [{ name: "Senior Member", age: 70, conditions: ["elderly", "copd"] }],
    rooms: [
      { name: "Front Veranda", ext_windows: 2, road_facing: true, kitchen_adjacent: false, large_volume: true },
      { name: "Inner Quiet Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "clinic_visit", name: "Clinic / Pharmacy Visit (6 km)", flexibility: "fixed", planned_hour: 10, duration_min: 40, activity_level: "seated", member_name: "Senior Member", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "senior_walk", name: "Morning Park Walk", flexibility: "flexible", planned_hour: 6, duration_min: 45, activity_level: "elderly_walk", member_name: "Senior Member", current_mask: "cloth", is_commute: false, is_work_shift: false },
      { id: "market_walk", name: "Vegetable Market Errand", flexibility: "flexible", planned_hour: 8, duration_min: 30, activity_level: "light_walk", member_name: "Senior Member", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  delivery_riders: {
    user_category: "delivery_riders",
    budget_tier: "under_500",
    commute_mode: "two_wheeler_petrol",
    target_commute_mode: "two_wheeler_petrol",
    commute_km: 40.0,
    uses_agarbatti_or_coils: true,
    dry_sweeps: true,
    members: [{ name: "Delivery Rider", age: 29, conditions: ["outdoor_worker"] }],
    rooms: [
      { name: "Road-Side Room Entry", ext_windows: 1, road_facing: true, kitchen_adjacent: true, large_volume: false },
      { name: "Inner Sleeping Corner", ext_windows: 0, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "shift_morning", name: "Morning-Afternoon Delivery Shift (4h)", flexibility: "fixed", planned_hour: 8, duration_min: 240, activity_level: "running_or_outdoor_work", member_name: "Delivery Rider", current_mask: "cloth", is_commute: true, is_work_shift: true },
      { id: "shift_evening", name: "Evening Peak Delivery Shift (4h)", flexibility: "fixed", planned_hour: 17, duration_min: 240, activity_level: "running_or_outdoor_work", member_name: "Delivery Rider", current_mask: "cloth", is_commute: true, is_work_shift: true },
      { id: "lunch_rest", name: "Midday Tea / Stretch Break", flexibility: "flexible", planned_hour: 13, duration_min: 30, activity_level: "light_walk", member_name: "Delivery Rider", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  }
};

const TABS = [
  { id: "plan", label: "Today's Plan", shortLabel: "Today", Icon: CalendarClock },
  { id: "indoor", label: "Home & Indoor", shortLabel: "Home", Icon: Home },
  { id: "impact", label: "Impact & What-If", shortLabel: "What-If", Icon: Sliders },
  { id: "chat", label: "Ask AI", shortLabel: "Ask AI", Icon: MessageSquare }
];

function loadSavedHousehold() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveHousehold(config) {
  try {
    if (!config) return;
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
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

export default function App() {
  const [citiesMap, setCitiesMap] = useState(FALLBACK_CITIES);
  const [presets, setPresets] = useState([]);
  const [activeCategoryId, setActiveCategoryId] = useState("adults_commuters");
  const [activePresetId, setActivePresetId] = useState("delhi_family");
  const [planConfig, setPlanConfig] = useState(null);
  const [planResult, setPlanResult] = useState(null);
  const [activeTab, setActiveTab] = useState("plan");
  const [selectedMember, setSelectedMember] = useState("ALL");
  const [simulateStale, setSimulateStale] = useState(false);
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [showMathModal, setShowMathModal] = useState(false);
  const [cleanAirNoteOpen, setCleanAirNoteOpen] = useState(false);
  const [installModalOpen, setInstallModalOpen] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isStandalone, setIsStandalone] = useState(() => detectPlatform().isStandalone);
  const [emergencyBannerMsg, setEmergencyBannerMsg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingText, setLoadingText] = useState("Fetching live air data...");
  const [explaining, setExplaining] = useState(false);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [chatMessages, setChatMessages] = useState([
    {
      role: "assistant",
      text: "Ask anything about today's schedule, window timing, masks, or CO2 savings. Every answer is grounded strictly in Today's Live Data.",
      source: "system"
    }
  ]);

  const runPlan = useCallback(async (config, staleFlag, skipLlm = false, statusLabel = "Recalculating plan...") => {
    if (!config) return;
    setLoadingText(statusLabel);
    if (skipLlm) {
      setErrorMsg(null);
    } else {
      setExplaining(true);
      setErrorMsg(null);
    }

    try {
      const res = await generatePlan({
        ...config,
        simulate_stale: staleFlag,
        skip_llm: skipLlm
      });
      setPlanResult(res);
      if (res.evidence_bundle?.emergency_alert) {
        setEmergencyBannerMsg(res.evidence_bundle.emergency_message);
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
      setExplaining(false);
    }
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

  async function handleTriggerNativeInstall() {
    if (!deferredPrompt) return "unavailable";
    deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    if (choice?.outcome === "accepted") {
      setDeferredPrompt(null);
    }
    return choice?.outcome || "dismissed";
  }

  useEffect(() => {
    let mounted = true;
    Promise.all([fetchPresets(), fetchCities().catch(() => FALLBACK_CITIES)])
      .then(([list, citiesData]) => {
        if (!mounted) return;
        if (citiesData && Object.keys(citiesData).length) {
          setCitiesMap(citiesData);
        }
        if (!list.length) return;
        setPresets(list);
        const first = list[0];
        const saved = loadSavedHousehold();
        const initialConfig = {
          ...first,
          ...(saved || {}),
          user_category: saved?.user_category || "adults_commuters",
          city: "mumbai",
          language: "en",
          preset_id: saved ? null : first.id,
          area_name: null,
          state: null,
          lat: null,
          lon: null,
          walk_override_hour: null
        };
        setActiveCategoryId(saved?.user_category || "adults_commuters");
        setActivePresetId(saved ? null : first.id);
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
    runPlan(nextConfig, simulateStale, false, `Updating plan for ${CATEGORY_LABELS[catId] || "Household"}...`);
  }

  function handleSelectPreset(preset) {
    const catMap = {
      delhi_family: "adults_commuters",
      mumbai_student: "students_kids",
      pune_elderly: "seniors",
      delivery_rider: "delivery_riders"
    };
    const mappedCat = catMap[preset.id] || "adults_commuters";
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

  function handleCityChange(newCity) {
    if (!planConfig) return;
    const nextConfig = {
      ...planConfig,
      city: newCity,
      area_name: null,
      state: null,
      lat: null,
      lon: null,
      walk_override_hour: null
    };
    setPlanConfig(nextConfig);
    setGpsError(null);
    setLoading(true);
    runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
  }

  function handleAreaChange(selectedArea) {
    if (!planConfig) return;
    setGpsError(null);
    if (selectedArea === "__center__") {
      const nextConfig = { ...planConfig, area_name: null, state: null, lat: null, lon: null };
      setPlanConfig(nextConfig);
      setLoading(true);
      runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
      return;
    }
    const areas = citiesMap[planConfig.city]?.areas || [];
    const match = areas.find((a) => a.name === selectedArea);
    if (!match) return;
    const nextConfig = {
      ...planConfig,
      area_name: match.name,
      state: null,
      lat: match.lat,
      lon: match.lon
    };
    setPlanConfig(nextConfig);
    setLoading(true);
    runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
  }

  function handleSelectGeocode(item) {
    if (!planConfig || !item) return;
    setGpsError(null);
    const nextConfig = {
      ...planConfig,
      city: item.name,
      area_name: item.name,
      state: item.state || null,
      lat: item.lat,
      lon: item.lon,
      walk_override_hour: null
    };
    setPlanConfig(nextConfig);
    setLoading(true);
    runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
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
          const nextConfig = {
            ...planConfig,
            city: rev.city,
            area_name: rev.area_name,
            state: rev.state || null,
            lat,
            lon,
            walk_override_hour: null
          };
          setPlanConfig(nextConfig);
          setLocating(false);
          setLoading(true);
          runPlan(nextConfig, simulateStale, false, "Fetching live air data...");
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
    runPlan(nextConfig, simulateStale, true, "Recalculating plan...");
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
    runPlan(nextConfig, simulateStale, true, "Recalculating plan...");
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
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    handleSelectCategory("adults_commuters");
    setCustomizerOpen(false);
  }

  const bundle = planResult?.evidence_bundle;
  const isBusy = loading || locating || explaining;

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 via-slate-50 to-teal-50/30 pb-10">
      <HeaderBar
        citiesMap={citiesMap}
        city={planConfig?.city || "mumbai"}
        cityDisplay={bundle?.air_snapshot?.city_name || planConfig?.city}
        stateName={bundle?.air_snapshot?.state || planConfig?.state}
        onCityChange={handleCityChange}
        areaName={planConfig?.area_name || null}
        onAreaChange={handleAreaChange}
        onSelectGeocode={handleSelectGeocode}
        onUseMyLocation={handleUseMyLocation}
        locating={locating}
        gpsError={gpsError}
        language={planConfig?.language || "en"}
        onLanguageChange={handleLanguageChange}
        suggestedLanguage={bundle?.air_snapshot?.suggested_language}
        simulateStale={simulateStale}
        loading={loading}
        canPromptInstall={Boolean(deferredPrompt)}
        isStandalone={isStandalone}
        onOpenInstallModal={() => setInstallModalOpen(true)}
      />

      <main className="mx-auto max-w-5xl space-y-5 px-4 pt-6 sm:px-6">
        <EmergencyBanner
          message={emergencyBannerMsg}
          onDismiss={() => setEmergencyBannerMsg(null)}
        />

        {errorMsg && (
          <div className="rounded-2xl bg-rose-50 px-4 py-3 text-xs font-semibold text-rose-900 ring-1 ring-rose-200">
            {errorMsg}
          </div>
        )}

        {/* Responsive Loading Status Strip */}
        {isBusy && bundle && (
          <div className="flex items-center gap-2 rounded-2xl bg-teal-900/95 px-4 py-2 text-xs font-semibold text-white shadow-sm">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-300" />
            <span>{loadingText}</span>
          </div>
        )}

        <PersonaBar
          activeCategoryId={activeCategoryId}
          onSelectCategory={handleSelectCategory}
          presets={presets}
          activePresetId={activePresetId}
          onSelectPreset={handleSelectPreset}
          onOpenCustomizer={() => setCustomizerOpen(true)}
        />

        {loading && !bundle ? (
          <div className="space-y-4 rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200/70">
            <div className="flex items-center justify-center gap-2.5 text-sm font-semibold text-slate-600">
              <Loader2 className="h-5 w-5 animate-spin text-teal-700" />
              <span>{loadingText}</span>
            </div>
            <div className="h-28 animate-pulse rounded-2xl bg-slate-100" />
            <div className="grid grid-cols-2 gap-3">
              <div className="h-20 animate-pulse rounded-2xl bg-slate-100" />
              <div className="h-20 animate-pulse rounded-2xl bg-slate-100" />
            </div>
          </div>
        ) : (
          bundle && (
            <>
              <HeroAirCard
                bundle={bundle}
                onJumpToImpact={() => setActiveTab("impact")}
              />

              {/* 4-Tab Segmented Control (in-flow below Hero so nothing overlaps Hero) */}
              <nav
                aria-label="Dashboard sections"
                className="relative z-10 rounded-2xl bg-white p-1.5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/80"
              >
                <div className="grid grid-cols-4 gap-1">
                  {TABS.map(({ id, label, shortLabel, Icon }) => {
                    const active = activeTab === id;
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setActiveTab(id)}
                        className={`flex flex-col items-center justify-center gap-0.5 rounded-xl px-1.5 py-2 text-[11px] font-bold transition sm:flex-row sm:gap-1.5 sm:px-3 sm:py-2.5 sm:text-xs ${active
                          ? "bg-slate-900 text-white shadow-sm"
                          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                          }`}
                      >
                        <Icon className={`h-3.5 w-3.5 shrink-0 ${active ? "text-teal-300" : "text-slate-500"}`} />
                        <span className="sm:hidden">{shortLabel}</span>
                        <span className="hidden truncate sm:inline">{label}</span>
                      </button>
                    );
                  })}
                </div>
              </nav>

              {activeTab === "plan" && (
                <div className="space-y-5">
                  {bundle.air_snapshot.current_naqi > 150 && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-xs text-amber-950 ring-1 ring-amber-200">
                      <div className="flex items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-amber-700" />
                        <span>
                          <strong>Elevated Smog (NAQI {bundle.air_snapshot.current_naqi}):</strong> Generate a polite
                          indoor-assembly or shift-timing note for school or work.
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setCleanAirNoteOpen(true)}
                        className="rounded-full bg-amber-900 px-3.5 py-1.5 text-xs font-bold text-white transition hover:bg-amber-800"
                      >
                        Generate School / Office Note
                      </button>
                    </div>
                  )}
                  <SmogChartCard airSnapshot={bundle.air_snapshot} profileSummary={bundle.profile_summary} />
                  <RoutineTimeline
                    bundle={bundle}
                    routinePlan={bundle.routine_plan}
                    members={planConfig?.members || []}
                    selectedMember={selectedMember}
                    onSelectMember={setSelectedMember}
                    narrative={planResult.narrative}
                    narrativeSource={planResult.narrative_source}
                    validatorPassed={planResult.validator_passed}
                    explaining={explaining}
                    onExplainWithGemini={() => runPlan(planConfig, simulateStale, false, "Recalculating plan...")}
                    onOpenCleanAirNote={() => setCleanAirNoteOpen(true)}
                  />
                  <FiveDayOutlookCard dailyOutlook={bundle.air_snapshot.daily_outlook} />
                </div>
              )}

              {activeTab === "indoor" && (
                <IndoorSanctuaryCard
                  sanctuaryPlan={bundle.sanctuary_plan}
                  currentNaqi={bundle.air_snapshot.current_naqi}
                  currentCategory={bundle.air_snapshot.current_category}
                  city={bundle.air_snapshot.city_name || planConfig?.city || "mumbai"}
                  areaName={bundle.air_snapshot.area_name || planConfig?.area_name || null}
                  language={planConfig?.language || "en"}
                  onOpenPermissions={() => setInstallModalOpen(true)}
                />
              )}

              {activeTab === "impact" && (
                <DualImpactLedgers
                  breatheLess={bundle.breathe_less}
                  emitLess={bundle.emit_less}
                  goldenStartHour={bundle.air_snapshot.golden_window.start_hour}
                  walkOverrideHour={planConfig?.walk_override_hour ?? null}
                  onWalkHourChange={handleWalkHourChange}
                  onResetWalkHour={handleResetWalkHour}
                  targetCommuteMode={planConfig?.target_commute_mode || "electric_metro"}
                  onTargetCommuteChange={handleTargetCommuteChange}
                  commuteKm={planConfig?.commute_km ?? 16}
                  onCommuteKmChange={handleCommuteKmChange}
                  onOpenMath={() => setShowMathModal(true)}
                />
              )}

              {/* Keep GeminiChatDrawer mounted so chat history persists across tabs */}
              <div className={activeTab === "chat" ? "block" : "hidden"}>
                <GeminiChatDrawer
                  evidenceBundle={bundle}
                  language={planConfig?.language || "en"}
                  messages={chatMessages}
                  onAddMessage={(msg) => setChatMessages((prev) => [...prev, msg])}
                  onSendMessage={sendChatQuestion}
                  onEmergencyTriggered={(msg) => setEmergencyBannerMsg(msg)}
                  onOpenPermissions={() => setInstallModalOpen(true)}
                />
              </div>

              <DataFooter
                provenance={bundle.provenance}
                simulateStale={simulateStale}
                onToggleStale={handleToggleStale}
                onOpenMath={() => setShowMathModal(true)}
                onOpenAppPermissions={() => setInstallModalOpen(true)}
              />
            </>
          )
        )}
      </main>

      <HouseholdCustomizer
        open={customizerOpen}
        onClose={() => setCustomizerOpen(false)}
        planConfig={planConfig}
        onUpdateConfig={handleUpdateCustomConfig}
        onResetSaved={handleResetSavedHousehold}
        saving={explaining}
      />

      <ShowMathModal
        open={showMathModal}
        onClose={() => setShowMathModal(false)}
        bundle={bundle}
      />

      <CleanAirNoteModal
        open={cleanAirNoteOpen}
        onClose={() => setCleanAirNoteOpen(false)}
        bundle={bundle}
      />

      <AppInstallPermissionsModal
        open={installModalOpen}
        onClose={() => setInstallModalOpen(false)}
        canPromptInstall={Boolean(deferredPrompt)}
        onTriggerNativeInstall={handleTriggerNativeInstall}
        onRequestLocation={handleUseMyLocation}
      />
    </div>
  );
}
