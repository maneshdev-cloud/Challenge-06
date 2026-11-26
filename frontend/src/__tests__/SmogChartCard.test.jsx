import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import SmogChartCard from "../components/SmogChartCard";
import { getHourMeta } from "../components/HourlySlotStrip";

const SAMPLE_HOURLY = Array.from({ length: 24 }, (_, h) => ({
  hour: h,
  time_label: `${String(h).padStart(2, "0")}:00`,
  pm2_5: h >= 13 && h <= 15 ? 42 : 120,
  cpcb_naqi: h >= 13 && h <= 15 ? 70 : 300,
  cpcb_category: h >= 13 && h <= 15 ? "Satisfactory" : "Very Poor",
  dominant_pollutant: "PM2.5",
  boundary_layer_height: h >= 13 && h <= 15 ? 1150 : 280,
  wind_speed_10m: 8.5
}));

const SAMPLE_AIR = {
  city: "delhi",
  city_name: "Delhi",
  current_hour: 8,
  meteorology_note: "Morning inversion lifts after noon.",
  meteorology_regime: "Winter Stagnant Inversion",
  morning_inversion_ceiling_m: 280,
  golden_window: {
    start_hour: 13,
    end_hour: 15,
    hours: [13, 14, 15],
    window_label: "1:00 PM - 3:00 PM",
    has_meaningful_window: true,
    advisory: "Shift outdoor activity to 1:00 PM - 3:00 PM."
  },
  hourly: SAMPLE_HOURLY
};

describe("SmogChartCard", () => {
  it("renders accessible chart summary and interactive hour strip without fade clipping", async () => {
    const user = userEvent.setup();

    render(
      <SmogChartCard
        airSnapshot={SAMPLE_AIR}
        profileSummary={{
          profile_key: "students_kids",
          profile_label: "Students & Kids",
          warning_threshold_naqi: 100
        }}
      />
    );

    expect(
      screen.getByRole("img", { name: /24-hour PM2\.5 and air mixing height chart for Delhi/i })
    ).toBeInTheDocument();

    const hourBtn = screen.getByRole("button", { name: /^2:00 PM,/i });
    expect(hourBtn).toHaveAttribute("aria-pressed", "false");

    await user.click(hourBtn);
    expect(hourBtn).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/2:00 PM:/)).toBeInTheDocument();
  });

  it("maps getHourMeta bands cleanly across profiles, thresholds, and fallback profile keys", () => {
    const ptGood = { hour: 14, pm2_5: 25, cpcb_naqi: 42 };
    const ptMod = { hour: 11, pm2_5: 75, cpcb_naqi: 135 };
    const ptHigh = { hour: 7, pm2_5: 260, cpcb_naqi: 410 };

    expect(getHourMeta(ptGood, [14], "seniors", 100)).toMatchObject({
      status: "Best",
      cue: "Best window"
    });
    expect(getHourMeta(ptGood, [14], "delivery_riders", 100)).toMatchObject({
      status: "Best",
      cue: "Wear N95 roadside"
    });
    expect(getHourMeta(ptMod, [], "seniors", 100)).toMatchObject({
      status: "Caution",
      cue: "Caution"
    });
    expect(getHourMeta(ptHigh, [], "unknown_profile")).toMatchObject({
      status: "Severe",
      cue: "Stay indoors"
    });
  });
});
