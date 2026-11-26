import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import DualImpactLedgers from "../components/DualImpactLedgers";
import IndoorSanctuaryCard from "../components/IndoorSanctuaryCard";
import RoutineTimeline from "../components/RoutineTimeline";

const SAMPLE_SANCTUARY_PLAN = {
  sanctuary_room: "Inner Bedroom",
  room_scores: [
    {
      name: "Inner Bedroom",
      score: 88,
      is_sanctuary: true,
      reason: "Away from street exhaust."
    },
    {
      name: "Street Living Room",
      score: 52,
      is_sanctuary: false,
      reason: "Faces traffic corridor."
    }
  ],
  window_advice: {
    action: "timed_open",
    open_window_start_hour: 13,
    open_window_end_hour: 15,
    duration_minutes: 25,
    outdoor_min_pm25: 42.5,
    modeled_indoor_baseline_pm25: 68.0,
    guidance: "Open balcony door briefly during midday trough."
  },
  personalized_alerts: ["Pause agarbatti today."],
  applicable_hacks: [
    {
      id: "tadka",
      tier: "Rs 0",
      max_cost_inr: 0,
      title: "Kitchen Tadka Isolation",
      action: "Close kitchen door before frying.",
      impact_note: "Avoids cooking PM2.5 spikes."
    }
  ],
  co2_safety_note: "Keep an interior gap open while sleeping.",
  no_houseplants_note: "Houseplants do not remove PM2.5 meaningfully."
};

const SAMPLE_BUNDLE = {
  air_snapshot: {
    city: "mumbai",
    city_name: "Mumbai",
    area_name: "Andheri",
    current_pm25: 72.5,
    current_naqi: 142,
    current_category: "Moderate",
    golden_window: { window_label: "1:00 PM - 3:00 PM" }
  },
  sanctuary_plan: { sanctuary_room: "Inner Bedroom" },
  breathe_less: {
    label: "Modeled Estimate",
    reduction_pct: 48,
    dose_avoided_ug: 52.4,
    baseline_dose_ug: 109.1,
    optimized_dose_ug: 56.7,
    cigarettes_avoided: 0.16
  },
  emit_less: {
    label: "Modeled Estimate",
    co2_saved_g: 2100,
    co2_saved_kg: 2.1,
    tailpipe_pm25_saved_mg: 88,
    phone_charges_saved: 256,
    commute_km: 14,
    baseline_mode_label: "Petrol Car (Solo)",
    target_mode_label: "Electric Metro"
  }
};

const SAMPLE_ROUTINE = [
  {
    id: "act_walk",
    name: "Morning Walk",
    member_name: "Dadi",
    flexibility: "flexible",
    badge: "FLEXIBLE • SHIFTED",
    original_hour: 7,
    recommended_hour: 14,
    duration_min: 30,
    recommended_pm25: 42.5,
    recommended_naqi: 71,
    recommended_mask: "none",
    dose_avoided_ug: 22.4,
    mitigation_steps: ["Shift walk to afternoon mixing trough."]
  },
  {
    id: "act_commute",
    name: "Office Commute",
    member_name: "Rohan",
    flexibility: "fixed",
    badge: "FIXED • MITIGATED",
    original_hour: 9,
    recommended_hour: 9,
    duration_min: 45,
    recommended_pm25: 95.0,
    recommended_naqi: 217,
    recommended_mask: "n95",
    dose_avoided_ug: 30.0,
    mitigation_steps: ["Wear fitted N95 mask on platforms."]
  }
];

describe("IndoorSanctuaryCard", () => {
  it("renders ranked rooms with accessible progressbars, window protocol, and safety notes", () => {
    render(
      <IndoorSanctuaryCard
        sanctuaryPlan={SAMPLE_SANCTUARY_PLAN}
        currentNaqi={220}
        currentCategory="Poor"
        city="mumbai"
        areaName="Andheri"
      />
    );

    expect(screen.getByText("Safest")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Inner Bedroom sanctuary safety score" })).toHaveAttribute(
      "aria-valuenow",
      "88"
    );
    expect(screen.getByText(/Open Windows \(1:00 PM – 3:00 PM • 25 Min\)/)).toBeInTheDocument();
    expect(screen.getByText("Pause agarbatti today.")).toBeInTheDocument();
    expect(screen.getByText("Kitchen Tadka Isolation")).toBeInTheDocument();
    expect(screen.getByText("Pause Heavy Cardio Today")).toBeInTheDocument();
    expect(screen.getByText("Audit My Room Photo")).toBeInTheDocument();
  });
});

describe("DualImpactLedgers", () => {
  it("renders separated health/emissions ledgers and triggers interactive callbacks", async () => {
    const user = userEvent.setup();
    const onWalkHourChange = vi.fn();
    const onCommuteKmChange = vi.fn();
    const onResetWalkHour = vi.fn();
    const onOpenMath = vi.fn();

    render(
      <DualImpactLedgers
        breatheLess={SAMPLE_BUNDLE.breathe_less}
        emitLess={SAMPLE_BUNDLE.emit_less}
        goldenStartHour={14}
        walkOverrideHour={16}
        onWalkHourChange={onWalkHourChange}
        onResetWalkHour={onResetWalkHour}
        targetCommuteMode="electric_metro"
        onTargetCommuteChange={vi.fn()}
        commuteKm={14}
        onCommuteKmChange={onCommuteKmChange}
        onOpenMath={onOpenMath}
      />
    );

    expect(screen.getByText("48% less pollution breathed")).toBeInTheDocument();
    expect(screen.getByText(/Low-smog day/)).toBeInTheDocument();
    expect(screen.getByText("~256 smartphone charges")).toBeInTheDocument();
    expect(screen.getByLabelText("Daily Travel Distance")).toHaveAttribute(
      "aria-valuetext",
      "14 kilometers"
    );

    fireEvent.change(screen.getByLabelText("Test Walk / Play Hour"), { target: { value: "13" } });
    expect(onWalkHourChange).toHaveBeenCalledWith(13);

    await user.click(screen.getByRole("button", { name: /Reset Best Hour/i }));
    expect(onResetWalkHour).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /Show Math & Sources/i }));
    expect(onOpenMath).toHaveBeenCalledTimes(1);
  });
});

describe("RoutineTimeline", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("supports member filtering, high-contrast Listen/Stop TTS toggle, and plan copy", async () => {
    const user = userEvent.setup();
    const onSelectMember = vi.fn();
    const speakMock = vi.fn();
    const cancelMock = vi.fn();

    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class MockUtterance {
        constructor(text) {
          this.text = text;
        }
      }
    );
    vi.stubGlobal("speechSynthesis", {
      speak: speakMock,
      cancel: cancelMock,
      getVoices: () => []
    });

    render(
      <RoutineTimeline
        bundle={SAMPLE_BUNDLE}
        routinePlan={SAMPLE_ROUTINE}
        members={[{ name: "Dadi" }, { name: "Rohan" }]}
        selectedMember="ALL"
        onSelectMember={onSelectMember}
        narrative="Today's Air:\nPM2.5 is 72.5 ug/m3."
        narrativeSource="gemini"
        validatorPassed
        onExplainWithGemini={vi.fn()}
        explaining={false}
        onOpenCleanAirNote={vi.fn()}
      />
    );

    expect(screen.getByText("Shifted to Cleaner Hour")).toBeInTheDocument();
    expect(screen.getByText("Fixed • Protected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dadi" }));
    expect(onSelectMember).toHaveBeenCalledWith("Dadi");

    const listenBtn = screen.getByRole("button", { name: "Listen to daily brief" });
    expect(listenBtn).toHaveClass("bg-teal-700", "text-white");
    await user.click(listenBtn);
    expect(speakMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Stop voice brief" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Copy \/ Share Today's Plan/i }));
    expect(await screen.findByText("Copied for WhatsApp!")).toBeInTheDocument();
  });
});
