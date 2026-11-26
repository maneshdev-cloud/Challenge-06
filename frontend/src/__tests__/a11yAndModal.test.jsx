import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Modal from "../components/Modal";

const { mockSendChatQuestion, SAMPLE_BUNDLE } = vi.hoisted(() => ({
  mockSendChatQuestion: vi.fn().mockResolvedValue({
    reply: "Grounded reply",
    emergency_alert: false,
    emergency_message: null,
    source: "deterministic_template",
    validator_passed: true
  }),
  SAMPLE_BUNDLE: {
    app_name: "PRANA-AI",
    city: "mumbai",
    city_name: "Mumbai",
    area_name: null,
    language: "en",
    budget_tier: "rs_0",
    emergency_alert: false,
    provenance: {
      source: "Open-Meteo",
      is_stale: false,
      is_fallback_replay: false,
      is_partial_fallback: false,
      data_type: "live_forecast",
      fetched_at_ist: "2026-11-25T09:00:00+05:30"
    },
    air_snapshot: {
      city: "mumbai",
      city_name: "Mumbai",
      current_hour: 9,
      current_pm25: 45,
      current_naqi: 75,
      current_category: "Satisfactory",
      dominant_pollutant: "PM2.5",
      morning_inversion_ceiling_m: 320,
      meteorology_regime: "Moderate",
      meteorology_note: "Sea breeze helps afternoon mixing.",
      golden_window: {
        start_hour: 13,
        end_hour: 15,
        hours: [13, 14],
        window_label: "13:00 - 15:00",
        mean_pm25: 35,
        mean_naqi: 58,
        morning_peak_pm25: 65,
        reduction_pct: 46,
        has_meaningful_window: true,
        is_clean_air_day: true,
        advisory: "Clean air day."
      },
      hourly: Array.from({ length: 24 }, (_, h) => ({
        hour: h,
        time_label: `${String(h).padStart(2, "0")}:00`,
        pm2_5: 45,
        pm10: 65,
        nitrogen_dioxide: 25,
        cpcb_naqi: 75,
        cpcb_category: "Satisfactory",
        dominant_pollutant: "PM2.5",
        temperature_2m: 26,
        relative_humidity_2m: 65,
        wind_speed_10m: 9,
        boundary_layer_height: 450
      })),
      daily_outlook: []
    },
    routine_plan: [
      {
        id: "walk",
        name: "Evening Walk",
        member_name: "Commuter",
        flexibility: "flexible",
        badge: "FLEXIBLE • KEPT",
        original_hour: 18,
        recommended_hour: 13,
        duration_min: 30,
        original_pm25: 55,
        recommended_pm25: 35,
        original_naqi: 92,
        recommended_naqi: 58,
        recommended_mask: "none",
        baseline_dose_ug: 25,
        optimized_dose_ug: 16,
        dose_avoided_ug: 9,
        mitigation_steps: ["Walk at 1 PM."],
        rationale: "Cleaner midday air."
      }
    ],
    sanctuary_plan: {
      sanctuary_room: "Inner Bedroom",
      room_scores: [
        {
          name: "Inner Bedroom",
          score: 85,
          ext_windows: 1,
          road_facing: false,
          kitchen_adjacent: false,
          large_volume: false,
          is_sanctuary: true,
          reason: "Away from road"
        }
      ],
      window_advice: {
        action: "timed_open",
        open_window_start_hour: 13,
        open_window_end_hour: 14,
        duration_minutes: 20,
        outdoor_min_pm25: 35,
        modeled_indoor_baseline_pm25: 38,
        modeled_post_cooking_pm25: 258,
        guidance: "Open non-road-facing windows 20 min."
      },
      co2_safety_note: "Leave inner door slightly ajar overnight.",
      no_houseplants_note: "Focus on source control and ventilation.",
      applicable_hacks: [],
      personalized_alerts: []
    },
    breathe_less: {
      baseline_dose_ug: 25,
      optimized_dose_ug: 16,
      dose_avoided_ug: 9,
      reduction_pct: 36,
      cigarettes_avoided: 0.03,
      label: "Modeled Estimate",
      formula_summary: "D = sum C * k * VE * dt",
      substitutions: [],
      limitations: "Modeled proxy."
    },
    emit_less: {
      baseline_mode: "car_petrol_solo",
      target_mode: "electric_metro",
      baseline_mode_label: "Petrol Car",
      target_mode_label: "Electric Metro",
      commute_km: 12,
      co2_saved_g: 1500,
      co2_saved_kg: 1.5,
      tailpipe_pm25_saved_mg: 40,
      phone_charges_saved: 183,
      label: "Modeled Estimate",
      formula_summary: "CO2e saved",
      substitutions: [],
      limitations: "ARAI average."
    },
    profile_summary: {
      profile_key: "adults_commuters",
      profile_label: "Adults & Commuters",
      sensitivity_tier: "Standard",
      warning_threshold_naqi: 150,
      warning_active: false,
      risk_level: "Standard",
      risk_badge: "Standard Watch",
      warning_banner: "Air stays satisfactory.",
      peak_ventilation_m3_hr: 1.25,
      total_outdoor_min: 30,
      tailored_hero_headline: "Normal outdoor routine is fine.",
      physiology_note: "Moderate breathing rate."
    }
  }
}));

vi.mock("../api/client", () => ({
  fetchPresets: vi.fn().mockResolvedValue([]),
  fetchCities: vi.fn().mockResolvedValue({}),
  generatePlan: vi.fn().mockResolvedValue({
    evidence_bundle: SAMPLE_BUNDLE,
    evidence_signature: "sig-server-999",
    narrative: "Today's Air:\nSatisfactory.\n\nDo This:\n- Enjoy walk.\n\nAvoid This:\n- Traffic.",
    narrative_source: "deterministic_template",
    validator_passed: true
  }),
  sendChatQuestion: (...args) => mockSendChatQuestion(...args),
  reverseGeocode: vi.fn(),
  searchIndianLocations: vi.fn().mockResolvedValue([])
}));

vi.mock("../components/SmogChartCard", () => ({
  default: () => <div data-testid="smog-chart-mock" />
}));

import App from "../App";

function ModalRerenderHarness() {
  const [text, setText] = useState("");
  const [closedCount, setClosedCount] = useState(0);
  return (
    <div>
      <span data-testid="closed-count">{closedCount}</span>
      <Modal
        open={true}
        onClose={() => setClosedCount((c) => c + 1)}
        labelledBy="modal-harness-title"
      >
        <h2 id="modal-harness-title">Edit Room</h2>
        <input
          aria-label="Room Name"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </Modal>
    </div>
  );
}

describe("Modal stability and dashboard WAI-ARIA navigation", () => {
  it("preserves input focus inside Modal across parent re-renders with inline onClose", async () => {
    const user = userEvent.setup();
    render(<ModalRerenderHarness />);

    const input = screen.getByLabelText("Room Name");
    input.focus();
    expect(document.activeElement).toBe(input);

    await user.type(input, "Study");
    expect(input).toHaveValue("Study");
    expect(document.activeElement).toBe(input);

    await user.keyboard("{Escape}");
    expect(screen.getByTestId("closed-count")).toHaveTextContent("1");
  });

  it("supports WAI-ARIA arrow/Home/End tablist keys and forwards HMAC evidence_signature", async () => {
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole("tablist", { name: "Dashboard sections" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);
    tabs.forEach((tab) => {
      const panelId = tab.getAttribute("aria-controls");
      expect(panelId).toBeTruthy();
      expect(document.getElementById(panelId)).toBeInTheDocument();
    });
    expect(document.getElementById("panel-plan")).not.toHaveAttribute("hidden");
    expect(document.getElementById("panel-indoor")).toHaveAttribute("hidden");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");

    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tabs[1]);

    await user.keyboard("{End}");
    expect(tabs[3]).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tabs[3]);

    await user.keyboard("{ArrowLeft}");
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Home}");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    await user.click(tabs[3]);
    await user.click(screen.getByRole("button", { name: "Can my dad still walk at 7 AM?" }));
    expect(mockSendChatQuestion).toHaveBeenCalledWith(
      "Can my dad still walk at 7 AM?",
      SAMPLE_BUNDLE,
      "en",
      "sig-server-999"
    );
  });
});
