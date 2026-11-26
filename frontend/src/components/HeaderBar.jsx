import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Download, Globe, Loader2, MapPin, Wind } from "lucide-react";
import { LANGUAGES, QUICK_CITIES } from "../data/constants";
import LocationSearchPopover from "./LocationSearchPopover";

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

  const locRef = useRef(null);
  const locButtonRef = useRef(null);
  const langRef = useRef(null);
  const langButtonRef = useRef(null);

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
    if (!locOpen && !langOpen) return;
    function handleOutside(e) {
      if (locOpen && locRef.current && !locRef.current.contains(e.target)) setLocOpen(false);
      if (langOpen && langRef.current && !langRef.current.contains(e.target)) setLangOpen(false);
    }
    function handleEscape(e) {
      if (e.key !== "Escape") return;
      if (locOpen) {
        setLocOpen(false);
        locButtonRef.current?.focus();
      }
      if (langOpen) {
        setLangOpen(false);
        langButtonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [locOpen, langOpen]);

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-4 sm:px-6">
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
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${active ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                    }`}
                >
                  {qc.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div ref={locRef} className="relative">
            <button
              ref={locButtonRef}
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
              <LocationSearchPopover
                citiesMap={citiesMap}
                cityKeyLower={cityKeyLower}
                isFeaturedCity={isFeaturedCity}
                activeCityMeta={activeCityMeta}
                areas={areas}
                areaName={areaName}
                locating={locating}
                gpsError={gpsError}
                onClose={(restoreFocus = false) => {
                  setLocOpen(false);
                  if (restoreFocus === true) locButtonRef.current?.focus();
                }}
                onCityChange={onCityChange}
                onAreaChange={onAreaChange}
                onSelectGeocode={onSelectGeocode}
                onUseMyLocation={onUseMyLocation}
              />
            )}
          </div>

          <div ref={langRef} className="relative">
            <button
              ref={langButtonRef}
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
                      className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${language === l.key ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
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
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${canPromptInstall && !isStandalone
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
