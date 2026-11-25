import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Crosshair, Download, Globe, Loader2, MapPin, Search, Wind, X } from "lucide-react";
import { searchIndianLocations } from "../api/client";
import { LANGUAGES, QUICK_CITIES } from "../data/constants";

export default function HeaderBar({
  citiesMap,
  city,
  cityDisplay,
  stateName,
  onCityChange,
  areaName,
  onAreaChange,
  onSelectGeocode,
  onUseMyLocation,
  locating,
  gpsError,
  language,
  onLanguageChange,
  suggestedLanguage,
  simulateStale,
  loading,
  canPromptInstall,
  isStandalone,
  onOpenInstallModal
}) {
  const [locOpen, setLocOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const locRef = useRef(null);
  const langRef = useRef(null);

  const cityKeyLower = city?.toLowerCase();
  const isFeaturedCity = Boolean(citiesMap?.[cityKeyLower]);
  const activeCityMeta = isFeaturedCity ? citiesMap[cityKeyLower] : null;
  const areas = activeCityMeta?.areas || [];

  const currentLangMeta = LANGUAGES.find((l) => l.key === language) || LANGUAGES[0];
  const localLangKey = suggestedLanguage || activeCityMeta?.local_language;
  const localLangMeta = LANGUAGES.find((l) => l.key === localLangKey);

  const locationLabel = areaName
    ? areaName.toLowerCase() === (cityDisplay || city || "").toLowerCase()
      ? stateName
        ? `${cityDisplay || city}, ${stateName}`
        : cityDisplay || city
      : `${areaName}, ${cityDisplay || city}`
    : stateName
      ? `${cityDisplay || city}, ${stateName}`
      : cityDisplay || city;

  useEffect(() => {
    function handleOutside(e) {
      if (locRef.current && !locRef.current.contains(e.target)) setLocOpen(false);
      if (langRef.current && !langRef.current.contains(e.target)) setLangOpen(false);
    }
    function handleEscape(e) {
      if (e.key === "Escape") {
        setLocOpen(false);
        setLangOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (trimmed.length < 2) {
      setSearchResults([]);
      setSearching(false);
      return undefined;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      searchIndianLocations(trimmed, 5)
        .then((res) => {
          if (!cancelled) setSearchResults(res || []);
        })
        .catch(() => {
          if (!cancelled) setSearchResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 260);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [searchQuery]);

  async function handleSearchSubmit(e) {
    e.preventDefault();
    const trimmed = searchQuery.trim();
    if (trimmed.length < 2) return;
    if (searchResults.length > 0) {
      pickGeocode(searchResults[0]);
      return;
    }
    setSearching(true);
    try {
      const res = await searchIndianLocations(trimmed, 5);
      setSearchResults(res || []);
      if (res && res.length > 0) pickGeocode(res[0]);
    } finally {
      setSearching(false);
    }
  }

  function pickGeocode(item) {
    setLocOpen(false);
    setSearchQuery("");
    setSearchResults([]);
    onSelectGeocode(item);
  }

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-4 sm:px-6">
        {/* Left: Brand + Desktop Quick Cities */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-slate-900 to-teal-700 text-white shadow-sm">
            <Wind className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <h1 className="whitespace-nowrap text-sm font-extrabold tracking-tight text-slate-900 sm:text-base">
              PRANA-AI
            </h1>
            {simulateStale && (
              <span className="hidden rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-900 sm:inline-flex">
                Offline Replay
              </span>
            )}
          </div>

          <div
            role="group"
            aria-label="Quick city selection"
            className="ml-2 hidden items-center gap-1 rounded-full bg-slate-100 p-1 md:flex"
          >
            {QUICK_CITIES.map((qc) => {
              const active = cityKeyLower === qc.key;
              return (
                <button
                  key={qc.key}
                  type="button"
                  disabled={loading}
                  aria-pressed={active}
                  onClick={() => onCityChange(qc.key)}
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                    active
                      ? "bg-white text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {qc.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Right: Location/Search Popover + Language Selector + App Install */}
        <div className="flex items-center gap-2">
          <div ref={locRef} className="relative">
            <button
              type="button"
              disabled={loading || locating}
              aria-expanded={locOpen}
              aria-haspopup="dialog"
              onClick={() => {
                setLangOpen(false);
                setLocOpen((v) => !v);
              }}
              aria-label={`Choose location or search Indian city (current: ${locationLabel})`}
              className="inline-flex max-w-[118px] items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1.5 text-xs font-semibold text-slate-800 transition hover:bg-slate-200/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 sm:max-w-[220px] sm:gap-1.5 sm:px-3"
            >
              {locating ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-teal-700" aria-hidden="true" />
              ) : (
                <MapPin className="h-3.5 w-3.5 shrink-0 text-teal-700" aria-hidden="true" />
              )}
              <span className="truncate">{locating ? "Detecting..." : locationLabel}</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
            </button>

            {locOpen && (
              <div
                role="dialog"
                aria-label="Location and pan-India city search"
                className="fixed inset-x-3 top-16 z-50 rounded-2xl border border-slate-200 bg-white p-4 shadow-2xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-96"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs font-extrabold uppercase tracking-wide text-slate-600">
                    Location &amp; Pan-India Search
                  </span>
                  <button
                    type="button"
                    onClick={() => setLocOpen(false)}
                    aria-label="Close location menu"
                    className="rounded-lg p-1 text-slate-600 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>

                <form onSubmit={handleSearchSubmit} className="flex items-center gap-1.5">
                  <div className="relative flex-1">
                    <label htmlFor="city-search-input" className="sr-only">
                      Search any Indian city or town
                    </label>
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
                      aria-hidden="true"
                    />
                    <input
                      id="city-search-input"
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search any city or town (Jaipur, Kochi...)"
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-8 pr-7 text-xs font-medium text-slate-900 placeholder:text-slate-500 focus:border-teal-600 focus:bg-white focus:outline-none"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        aria-label="Clear city search"
                        onClick={() => {
                          setSearchQuery("");
                          setSearchResults([]);
                        }}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-700"
                      >
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                  <button
                    type="submit"
                    disabled={searching || searchQuery.trim().length < 2}
                    className="rounded-xl bg-slate-900 px-3 py-2 text-xs font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-40"
                  >
                    Go
                  </button>
                </form>

                {searchQuery.trim().length >= 2 && (
                  <div className="mt-2 max-h-44 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50">
                    {searching ? (
                      <p className="px-3 py-2 text-xs text-slate-600">Searching across India...</p>
                    ) : searchResults.length === 0 ? (
                      <p className="px-3 py-2 text-xs text-slate-600">
                        No matching Indian location found.
                      </p>
                    ) : (
                      <ul className="divide-y divide-slate-100">
                        {searchResults.map((item, idx) => (
                          <li key={`${item.name}-${item.lat}-${idx}`}>
                            <button
                              type="button"
                              onClick={() => pickGeocode(item)}
                              className="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                            >
                              <span className="font-semibold text-slate-900">
                                {item.name}
                                {item.state ? `, ${item.state}` : ""}
                              </span>
                              <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 ring-1 ring-slate-200">
                                {item.is_coastal ? "Coastal" : "Inland"}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => {
                    setLocOpen(false);
                    onUseMyLocation();
                  }}
                  disabled={locating}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-teal-50 px-3 py-2 text-xs font-bold text-teal-800 ring-1 ring-teal-200 transition hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                >
                  <Crosshair
                    className={`h-3.5 w-3.5 ${locating ? "animate-spin" : ""}`}
                    aria-hidden="true"
                  />
                  {locating ? "Detecting your area..." : "Use My Location"}
                </button>

                {gpsError && (
                  <p
                    role="alert"
                    className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] font-medium text-amber-900"
                  >
                    {gpsError}
                  </p>
                )}

                <div className="mt-3.5">
                  <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                    Quick Cities
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_CITIES.map((qc) => {
                      const active = isFeaturedCity && cityKeyLower === qc.key;
                      return (
                        <button
                          key={qc.key}
                          type="button"
                          aria-pressed={active}
                          onClick={() => {
                            onCityChange(qc.key);
                            setLocOpen(false);
                          }}
                          className={`rounded-full px-2.5 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                            active
                              ? "bg-slate-900 text-white"
                              : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                          }`}
                        >
                          {qc.label}
                        </button>
                      );
                    })}
                    {citiesMap?.kolkata && (
                      <button
                        type="button"
                        aria-pressed={isFeaturedCity && cityKeyLower === "kolkata"}
                        onClick={() => {
                          onCityChange("kolkata");
                          setLocOpen(false);
                        }}
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                          isFeaturedCity && cityKeyLower === "kolkata"
                            ? "bg-slate-900 text-white"
                            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                        }`}
                      >
                        Kolkata
                      </button>
                    )}
                  </div>
                </div>

                {isFeaturedCity && areas.length > 0 && (
                  <div className="mt-3">
                    <label
                      htmlFor="area-locality-select"
                      className="block text-[11px] font-bold uppercase tracking-wide text-slate-600"
                    >
                      {activeCityMeta.name} Area / Locality
                    </label>
                    <select
                      id="area-locality-select"
                      value={areaName || "__center__"}
                      onChange={(e) => {
                        onAreaChange(e.target.value);
                        setLocOpen(false);
                      }}
                      className="mt-1.5 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-900 focus:border-teal-600 focus:outline-none"
                    >
                      <option value="__center__">{activeCityMeta.name} Center</option>
                      {areas.map((a) => (
                        <option key={a.name} value={a.name}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Language Popover Trigger */}
          <div ref={langRef} className="relative">
            <button
              type="button"
              disabled={loading}
              aria-expanded={langOpen}
              aria-haspopup="menu"
              onClick={() => {
                setLocOpen(false);
                setLangOpen((v) => !v);
              }}
              aria-label={`Choose language (current: ${currentLangMeta.label})`}
              className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-800 transition hover:bg-slate-200/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <Globe className="h-3.5 w-3.5 text-slate-600" aria-hidden="true" />
              <span className="hidden sm:inline">{currentLangMeta.label}</span>
              <span className="uppercase sm:hidden">{language}</span>
              <ChevronDown className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
            </button>

            {langOpen && (
              <div
                role="menu"
                aria-label="Available languages"
                className="absolute right-0 top-11 z-50 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl"
              >
                {localLangMeta && localLangKey !== language && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      onLanguageChange(localLangKey);
                      setLangOpen(false);
                    }}
                    className="mb-1.5 flex w-full items-center justify-between rounded-xl bg-teal-50 px-3 py-2 text-left text-xs font-bold text-teal-800 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                  >
                    <span>Try Local: {localLangMeta.label}</span>
                  </button>
                )}
                <div className="space-y-0.5">
                  {LANGUAGES.map((l) => (
                    <button
                      key={l.key}
                      type="button"
                      role="menuitemradio"
                      aria-checked={language === l.key}
                      onClick={() => {
                        onLanguageChange(l.key);
                        setLangOpen(false);
                      }}
                      className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                        language === l.key
                          ? "bg-slate-900 text-white"
                          : "text-slate-700 hover:bg-slate-100"
                      }`}
                    >
                      <span>{l.label}</span>
                      {language === l.key && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={onOpenInstallModal}
            aria-label={isStandalone ? "App permissions and info" : "Download or install PRANA-AI app"}
            title={isStandalone ? "App Permissions" : "Install App on iOS or Android"}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
              canPromptInstall && !isStandalone
                ? "bg-teal-700 text-white shadow-sm hover:bg-teal-800"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200/80"
            }`}
          >
            <Download className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="hidden sm:inline">{isStandalone ? "App" : "Get App"}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
