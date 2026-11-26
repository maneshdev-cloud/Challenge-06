import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CleanAirNoteModal from "../components/CleanAirNoteModal";
import { computeCommunityImpact, generateCleanWindowIcs } from "../utils/communityAndCalendar";

const BUNDLE = {
  city: "delhi",
  air_snapshot: {
    city: "delhi",
    city_name: "Delhi",
    area_name: "Dwarka",
    current_pm25: 142.0,
    current_naqi: 318,
    current_category: "Very Poor",
    golden_window: {
      start_hour: 13,
      end_hour: 15,
      hours: [13, 14],
      window_label: "13:00 - 15:00",
      mean_pm25: 94.0,
      mean_naqi: 210,
      morning_peak_pm25: 215.0,
      reduction_pct: 56.3,
      has_meaningful_window: true,
      is_clean_air_day: false,
      advisory: "Lowest-exposure window is 13:00 - 15:00."
    }
  },
  breathe_less: { dose_avoided_ug: 45.0 },
  emit_less: { co2_saved_kg: 1.5, tailpipe_pm25_saved_mg: 40.0 }
};

describe("communityAndCalendar + CleanAirNoteModal RWA & .ics", () => {
  it("computes scaled RWA society metrics and valid RFC 5545 IST .ics output", () => {
    const stats = computeCommunityImpact(BUNDLE, 100);
    expect(stats).toEqual({
      householdsCount: 100,
      dailyDoseSavedMg: 4.5,
      dailyCo2SavedKg: 150,
      monthlyCo2SavedKg: 4500,
      dailyTailpipePm25G: 4
    });

    const ics = generateCleanWindowIcs(BUNDLE, new Date("2026-11-26T06:00:00Z"));
    expect(ics).toContain("BEGIN:VCALENDAR");
    expect(ics).toContain("DTSTART;TZID=Asia/Kolkata:20261126T130000");
    expect(ics).toContain("DTEND;TZID=Asia/Kolkata:20261126T150000");
    expect(ics).toContain("SUMMARY:PRANA-AI Lowest-Smog Outdoor Window (Dwarka\\, Delhi");
    expect(ics).toContain("END:VCALENDAR");
  });

  it("switches to RWA / Society mode, scales participating homes, and triggers .ics download", async () => {
    const user = userEvent.setup();
    const createUrlSpy = vi.fn(() => "blob:mock-ics");
    const revokeSpy = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: createUrlSpy,
      revokeObjectURL: revokeSpy
    });

    render(<CleanAirNoteModal open onClose={vi.fn()} bundle={BUNDLE} />);
    await user.click(screen.getByRole("button", { name: /RWA \/ Society/i }));
    const homesInput = screen.getByLabelText(/Participating Homes/i);
    fireEvent.change(homesInput, { target: { value: "200" } });
    expect(screen.getByText(/~9000 kg CO2e\/mo/i)).toBeInTheDocument();
    expect(screen.getByText(/200 Participating Homes/i)).toBeInTheDocument();

    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await user.click(screen.getByRole("button", { name: /Calendar \(\.ics\)/i }));
    expect(createUrlSpy).toHaveBeenCalledTimes(1);
    expect(anchorClick).toHaveBeenCalledTimes(1);
    anchorClick.mockRestore();
  });
});
