import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "../components/ErrorBoundary";
import RoutineTimeline from "../components/RoutineTimeline";

function BrokenChild({ shouldThrow }) {
  if (shouldThrow) {
    throw new Error("Simulated render crash");
  }
  return <p>Healthy child rendered</p>;
}

describe("ErrorBoundary recovery and localized content lang attributes", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders accessible alert fallback on error and resets view cleanly", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    let triggerCrash = true;
    const { rerender } = render(
      <ErrorBoundary>
        <BrokenChild shouldThrow={triggerCrash} />
      </ErrorBoundary>
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("PRANA-AI encountered a display error");
    expect(alert).toHaveTextContent("Simulated render crash");

    triggerCrash = false;
    rerender(
      <ErrorBoundary>
        <BrokenChild shouldThrow={false} />
      </ErrorBoundary>
    );
    await user.click(screen.getByRole("button", { name: /reset view/i }));
    expect(screen.getByText("Healthy child rendered")).toBeInTheDocument();
  });

  it("applies localized lang attribute onto guidance output without mutating html root lang", () => {
    document.documentElement.lang = "en";
    const sampleBundle = {
      language: "hi",
      air_snapshot: {
        city_name: "Delhi",
        area_name: null,
        current_pm25: 180,
        current_naqi: 345,
        current_category: "Very Poor",
        golden_window: { window_label: "13:00 - 15:00" }
      },
      sanctuary_plan: { sanctuary_room: "Inner Bedroom" },
      breathe_less: { reduction_pct: 42, dose_avoided_ug: 85 },
      emit_less: { co2_saved_g: 900, co2_saved_kg: 0.9 }
    };

    render(
      <RoutineTimeline
        bundle={sampleBundle}
        routinePlan={[]}
        members={[]}
        selectedMember="ALL"
        onSelectMember={vi.fn()}
        narrative="आज की हवा: PM2.5 180 ug/m3 है।"
        narrativeSource="deterministic_template"
        validatorPassed={true}
        explaining={false}
      />
    );

    const guidance = screen.getByText(/आज की हवा/i).closest("[lang]");
    expect(guidance).toHaveAttribute("lang", "hi");
    expect(document.documentElement.lang).toBe("en");
  });
});
