import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import HeroAirCard from "../components/HeroAirCard";

const SAMPLE_BUNDLE = {
  air_snapshot: {
    city: "mumbai",
    city_name: "Mumbai",
    area_name: "Andheri",
    state: "Maharashtra",
    current_hour: 9,
    current_pm25: 72.5,
    current_naqi: 142,
    current_category: "Moderate",
    golden_window: {
      start_hour: 13,
      end_hour: 15,
      window_label: "1:00 PM - 3:00 PM",
      reduction_pct: 28,
      has_meaningful_window: true,
      is_clean_air_day: false
    }
  },
  breathe_less: {
    baseline_dose_ug: 92.4,
    optimized_dose_ug: 46.2,
    dose_avoided_ug: 46.2,
    reduction_pct: 50
  },
  emit_less: {
    co2_saved_g: 2100,
    co2_saved_kg: 2.1,
    tailpipe_pm25_saved_mg: 88,
    phone_charges_saved: 256
  },
  provenance: {
    is_fallback_replay: true
  },
  profile_summary: {
    profile_key: "seniors",
    profile_label: "Seniors (65+ / COPD)",
    risk_badge: "Senior Precaution",
    risk_level: "Elevated for Sensitive Airway",
    warning_active: true,
    warning_banner: "Senior Precaution Triggered (Est. AQI 142 > 100).",
    peak_ventilation_m3_hr: 1.3,
    total_outdoor_min: 75,
    tailored_hero_headline: "Move senior walk from cold smog to warmer 1:00 PM – 3:00 PM.",
    physiology_note: "Aged airways clear fine dust slower."
  }
};

describe("HeroAirCard", () => {
  it("renders honest Est. India AQI, replay tag, senior warning, and jump action", async () => {
    const user = userEvent.setup();
    const onJumpToImpact = vi.fn();

    render(<HeroAirCard bundle={SAMPLE_BUNDLE} onJumpToImpact={onJumpToImpact} />);

    expect(screen.getByText("Andheri, Mumbai")).toBeInTheDocument();
    expect(screen.getByText("Offline Replay")).toBeInTheDocument();
    expect(screen.getByText("Est. India AQI")).toBeInTheDocument();
    expect(screen.getByText("142")).toBeInTheDocument();
    expect(screen.getByText(/Senior Precaution Triggered/)).toBeInTheDocument();
    expect(screen.getByText(/~256 phone charges/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /50% less pollution breathed/i }));
    expect(onJumpToImpact).toHaveBeenCalledTimes(1);
  });
});
