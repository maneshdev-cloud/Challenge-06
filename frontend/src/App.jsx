import { useState } from "react";
import { FileText, Loader2 } from "lucide-react";
import { sendChatQuestion } from "./api/client";
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
import { TABS } from "./data/constants";
import usePranaPlan from "./hooks/usePranaPlan";

export default function App() {
  const {
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
  } = usePranaPlan();

  const [activeTab, setActiveTab] = useState("plan");
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [showMathModal, setShowMathModal] = useState(false);
  const [cleanAirNoteOpen, setCleanAirNoteOpen] = useState(false);
  const [installModalOpen, setInstallModalOpen] = useState(false);

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
          <div
            role="alert"
            className="rounded-2xl bg-rose-50 px-4 py-3 text-xs font-semibold text-rose-900 ring-1 ring-rose-200"
          >
            {errorMsg}
          </div>
        )}

        {isBusy && bundle && (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 rounded-2xl bg-teal-900/95 px-4 py-2 text-xs font-semibold text-white shadow-sm"
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-300" aria-hidden="true" />
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
          <div
            role="status"
            aria-live="polite"
            className="space-y-4 rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200/70"
          >
            <div className="flex items-center justify-center gap-2.5 text-sm font-semibold text-slate-600">
              <Loader2 className="h-5 w-5 animate-spin text-teal-700" aria-hidden="true" />
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

              {/* 4-Tab WAI-ARIA Tablist (in-flow below Hero so nothing overlaps Hero) */}
              <div
                className="relative z-10 rounded-2xl bg-white p-1.5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/80"
              >
                <div
                  role="tablist"
                  aria-label="Dashboard sections"
                  className="grid grid-cols-4 gap-1"
                >
                  {TABS.map(({ id, label, shortLabel, Icon }) => {
                    const active = activeTab === id;
                    return (
                      <button
                        key={id}
                        id={`tab-${id}`}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        aria-controls={`panel-${id}`}
                        onClick={() => setActiveTab(id)}
                        className={`flex flex-col items-center justify-center gap-0.5 rounded-xl px-1.5 py-2 text-[11px] font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 sm:flex-row sm:gap-1.5 sm:px-3 sm:py-2.5 sm:text-xs ${
                          active
                            ? "bg-slate-900 text-white shadow-sm"
                            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                        }`}
                      >
                        <Icon
                          className={`h-3.5 w-3.5 shrink-0 ${active ? "text-teal-300" : "text-slate-600"}`}
                          aria-hidden="true"
                        />
                        <span className="sm:hidden">{shortLabel}</span>
                        <span className="hidden truncate sm:inline">{label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {activeTab === "plan" && (
                <div
                  id="panel-plan"
                  role="tabpanel"
                  aria-labelledby="tab-plan"
                  className="space-y-5"
                >
                  {bundle.air_snapshot.current_naqi > 150 && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-xs text-amber-950 ring-1 ring-amber-200">
                      <div className="flex items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />
                        <span>
                          <strong>Elevated Smog (Est. AQI {bundle.air_snapshot.current_naqi}):</strong> Generate a
                          polite indoor-assembly or shift-timing note for school or work.
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setCleanAirNoteOpen(true)}
                        className="rounded-full bg-amber-900 px-3.5 py-1.5 text-xs font-bold text-white transition hover:bg-amber-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600"
                      >
                        Generate School / Office Note
                      </button>
                    </div>
                  )}
                  <SmogChartCard
                    airSnapshot={bundle.air_snapshot}
                    profileSummary={bundle.profile_summary}
                  />
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
                    onExplainWithGemini={() =>
                      runPlan(planConfig, simulateStale, false, "Recalculating plan...")
                    }
                    onOpenCleanAirNote={() => setCleanAirNoteOpen(true)}
                  />
                  <FiveDayOutlookCard dailyOutlook={bundle.air_snapshot.daily_outlook} />
                </div>
              )}

              {activeTab === "indoor" && (
                <div
                  id="panel-indoor"
                  role="tabpanel"
                  aria-labelledby="tab-indoor"
                >
                  <IndoorSanctuaryCard
                    sanctuaryPlan={bundle.sanctuary_plan}
                    currentNaqi={bundle.air_snapshot.current_naqi}
                    currentCategory={bundle.air_snapshot.current_category}
                    city={bundle.air_snapshot.city_name || planConfig?.city || "mumbai"}
                    areaName={bundle.air_snapshot.area_name || planConfig?.area_name || null}
                    language={planConfig?.language || "en"}
                    onOpenPermissions={() => setInstallModalOpen(true)}
                  />
                </div>
              )}

              {activeTab === "impact" && (
                <div
                  id="panel-impact"
                  role="tabpanel"
                  aria-labelledby="tab-impact"
                >
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
                </div>
              )}

              {/* Keep GeminiChatDrawer mounted so chat history persists across tabs */}
              <div
                id="panel-chat"
                role="tabpanel"
                aria-labelledby="tab-chat"
                hidden={activeTab !== "chat"}
                className={activeTab === "chat" ? "block" : "hidden"}
              >
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
        onResetSaved={() => {
          handleResetSavedHousehold();
          setCustomizerOpen(false);
        }}
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
