import { useEffect, useRef, useState } from "react";
import { Crosshair, Search, X } from "lucide-react";
import { searchIndianLocations } from "../api/client";
import { QUICK_CITIES } from "../data/constants";

export default function LocationSearchPopover({
  citiesMap,
  cityKeyLower,
  isFeaturedCity,
  activeCityMeta,
  areas,
  areaName,
  locating,
  gpsError,
  onClose,
  onCityChange,
  onAreaChange,
  onSelectGeocode,
  onUseMyLocation
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const submitSeqRef = useRef(0);

  useEffect(() => () => {
    submitSeqRef.current += 1;
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

  function pickGeocode(item) {
    onClose();
    setSearchQuery("");
    setSearchResults([]);
    onSelectGeocode(item);
  }

  async function handleSearchSubmit(e) {
    e.preventDefault();
    const trimmed = searchQuery.trim();
    if (trimmed.length < 2) return;
    if (searchResults.length > 0) {
      pickGeocode(searchResults[0]);
      return;
    }
    const seq = ++submitSeqRef.current;
    setSearching(true);
    try {
      const res = await searchIndianLocations(trimmed, 5);
      if (seq !== submitSeqRef.current) return;
      setSearchResults(res || []);
      if (res && res.length > 0) pickGeocode(res[0]);
    } catch {
      if (seq === submitSeqRef.current) setSearchResults([]);
    } finally {
      if (seq === submitSeqRef.current) setSearching(false);
    }
  }

  return (
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
          onClick={() => onClose(true)}
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
            onChange={(e) => {
              submitSeqRef.current += 1;
              setSearchQuery(e.target.value);
            }}
            placeholder="Search any city or town (Jaipur, Kochi...)"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-8 pr-7 text-xs font-medium text-slate-900 placeholder:text-slate-500 focus:border-teal-600 focus:bg-white focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              aria-label="Clear city search"
              onClick={() => {
                submitSeqRef.current += 1;
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
            <p className="px-3 py-2 text-xs text-slate-600">No matching Indian location found.</p>
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
          onClose();
          onUseMyLocation();
        }}
        disabled={locating}
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-teal-50 px-3 py-2 text-xs font-bold text-teal-800 ring-1 ring-teal-200 transition hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
      >
        <Crosshair className={`h-3.5 w-3.5 ${locating ? "animate-spin" : ""}`} aria-hidden="true" />
        {locating ? "Detecting your area..." : "Use My Location"}
      </button>

      {gpsError && (
        <p role="alert" className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] font-medium text-amber-900">
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
                  onClose();
                }}
                className={`rounded-full px-2.5 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                  active ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
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
                onClose();
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
              onClose();
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
  );
}
