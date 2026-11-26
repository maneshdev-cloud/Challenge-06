import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import FiveDayOutlookCard from "../components/FiveDayOutlookCard";
import GeminiChatDrawer from "../components/GeminiChatDrawer";
import HeaderBar from "../components/HeaderBar";
import LocationSearchPopover from "../components/LocationSearchPopover";
import ShowMathModal from "../components/ShowMathModal";

const SAMPLE_BUNDLE = {
  city: "delhi",
  air_snapshot: {
    current_pm25: 138.4,
    current_naqi: 314,
    current_category: "Very Poor",
    dominant_pollutant: "PM2.5",
    morning_inversion_ceiling_m: 190,
    meteorology_regime: "Indo-Gangetic Inversion"
  },
  breathe_less: {
    formula_summary: "D (ug) = sum_h (C_h * kappa * V_E * dt_h) * (1 - eta)",
    substitutions: ["Walk (30m): Saved 34.2 ug"],
    limitations: "Gridded CAMS model estimate, not a personal monitor."
  },
  emit_less: {
    formula_summary: "Delta CO2e = km * (EF_base - EF_new)",
    substitutions: ["CO2e = 10 km * (164 - 14) = 1500 g"],
    limitations: "ARAI / WRI India average emission factors."
  },
  provenance: {
    source: "Open-Meteo CAMS Global",
    data_type: "model_forecast",
    retrieved_at: "2026-11-25T10:00:00+05:30",
    spatial_note: "~40 km CAMS grid."
  }
};

describe("GeminiChatDrawer", () => {
  it("forwards HMAC signature, adds reply messages, and triggers medical emergency callback", async () => {
    const user = userEvent.setup();
    const onAddMessage = vi.fn();
    const onEmergencyTriggered = vi.fn();
    const onSendMessage = vi.fn().mockResolvedValueOnce({
      reply: "Call emergency services (108 / 112) immediately.",
      source: "emergency_triage",
      emergency_alert: true,
      emergency_message: "Call 108 / 112 now"
    });

    render(
      <GeminiChatDrawer
        evidenceBundle={SAMPLE_BUNDLE}
        evidenceSignature="deadbeef64hex"
        language="en"
        messages={[{ role: "assistant", text: "Ask anything.", source: "system" }]}
        onAddMessage={onAddMessage}
        onSendMessage={onSendMessage}
        onEmergencyTriggered={onEmergencyTriggered}
      />
    );

    const log = screen.getByRole("log", { name: "Conversation history" });
    expect(log).toHaveAttribute("aria-live", "polite");

    await user.click(screen.getByRole("button", { name: /My son is wheezing badly/i }));

    await waitFor(() => expect(onSendMessage).toHaveBeenCalledTimes(1));
    expect(onSendMessage).toHaveBeenCalledWith(
      "My son is wheezing badly",
      SAMPLE_BUNDLE,
      "en",
      "deadbeef64hex"
    );
    expect(onAddMessage).toHaveBeenCalledWith({ role: "user", text: "My son is wheezing badly" });
    expect(onAddMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "assistant",
        emergency: true,
        source: "emergency_triage"
      })
    );
    expect(onEmergencyTriggered).toHaveBeenCalledWith("Call 108 / 112 now");
  });

  it("allows typed question submission and keeps empty input button disabled", async () => {
    const user = userEvent.setup();
    const onSendMessage = vi.fn().mockResolvedValueOnce({
      reply: "Walk at 2:00 PM.",
      source: "gemini",
      emergency_alert: false
    });

    render(
      <GeminiChatDrawer
        evidenceBundle={SAMPLE_BUNDLE}
        evidenceSignature="sig123"
        language="en"
        messages={[]}
        onAddMessage={vi.fn()}
        onSendMessage={onSendMessage}
        onEmergencyTriggered={vi.fn()}
      />
    );

    const sendBtn = screen.getByRole("button", { name: /send/i });
    expect(sendBtn).toBeDisabled();

    const input = screen.getByLabelText(/Ask PRANA-AI a question/i);
    await user.type(input, "When is best to walk?");
    expect(sendBtn).toBeEnabled();
    await user.click(sendBtn);

    await waitFor(() =>
      expect(onSendMessage).toHaveBeenCalledWith(
        "When is best to walk?",
        SAMPLE_BUNDLE,
        "en",
        "sig123"
      )
    );
  });
});

describe("FiveDayOutlookCard and ShowMathModal", () => {
  it("renders traffic-light 5-day cards and scientific Show Math disclosures", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const days = [
      {
        date: "2026-11-25",
        day_label: "Today",
        peak_naqi: 85,
        peak_category: "Satisfactory",
        peak_pm25: 51,
        best_window_label: "1:00 PM - 3:00 PM",
        tip: "Cleaner midday breeze."
      },
      {
        date: "2026-11-26",
        day_label: "Thu",
        peak_naqi: 245,
        peak_category: "Poor",
        peak_pm25: 103,
        best_window_label: "2:00 PM - 4:00 PM",
        tip: "Keep morning walks indoors."
      }
    ];

    render(
      <>
        <FiveDayOutlookCard dailyOutlook={days} />
        <ShowMathModal open onClose={onClose} bundle={SAMPLE_BUNDLE} />
      </>
    );

    expect(screen.getByText("Next 5 Days Outlook")).toBeInTheDocument();
    expect(screen.getByText("Peak Est. AQI 85")).toBeInTheDocument();
    expect(screen.getByText("Peak Est. AQI 245")).toBeInTheDocument();

    expect(
      screen.getByRole("dialog")
    ).toBeInTheDocument();
    expect(screen.getByText(/Walk \(30m\): Saved 34.2 ug/)).toBeInTheDocument();
    expect(screen.getByText(/CO2e = 10 km/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close math modal" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores stale search submit responses after clear or typing changes", async () => {
    const user = userEvent.setup();
    const onSelectGeocode = vi.fn();
    let resolveSubmit;
    const searchSpy = vi
      .spyOn(await import("../api/client"), "searchIndianLocations")
      .mockResolvedValueOnce([])
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSubmit = resolve;
          })
      );

    render(
      <LocationSearchPopover
        citiesMap={{}}
        cityKeyLower="delhi"
        isFeaturedCity={false}
        activeCityMeta={null}
        areas={[]}
        areaName={null}
        locating={false}
        gpsError={null}
        onClose={vi.fn()}
        onCityChange={vi.fn()}
        onAreaChange={vi.fn()}
        onSelectGeocode={onSelectGeocode}
        onUseMyLocation={vi.fn()}
      />
    );

    const input = screen.getByLabelText("Search any Indian city or town");
    await user.type(input, "Jaipur");
    const goBtn = screen.getByRole("button", { name: "Go" });
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(goBtn).toBeEnabled());

    await user.click(goBtn);
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(2));
    expect(typeof resolveSubmit).toBe("function");

    await user.click(screen.getByRole("button", { name: "Clear city search" }));
    await act(async () => {
      resolveSubmit([{ name: "Jaipur", state: "Rajasthan", lat: 26.9, lon: 75.8 }]);
      await Promise.resolve();
    });
    expect(onSelectGeocode).not.toHaveBeenCalled();

    let resolveTypedSubmit;
    searchSpy.mockResolvedValueOnce([]).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveTypedSubmit = resolve;
        })
    );

    await user.type(input, "Kochi");
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(goBtn).toBeEnabled());

    await user.click(goBtn);
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(4));
    expect(typeof resolveTypedSubmit).toBe("function");

    await user.type(input, "s");
    await act(async () => {
      resolveTypedSubmit([{ name: "Kochi", state: "Kerala", lat: 9.93, lon: 76.26 }]);
      await Promise.resolve();
    });
    expect(onSelectGeocode).not.toHaveBeenCalled();
    searchSpy.mockRestore();
  });

  it("restores focus to location trigger on Escape or close button, but not on outside click", async () => {
    const user = userEvent.setup();
    render(
      <HeaderBar
        citiesMap={{}}
        city="delhi"
        cityDisplay="Delhi"
        stateName="Delhi"
        onCityChange={vi.fn()}
        areaName={null}
        onAreaChange={vi.fn()}
        onSelectGeocode={vi.fn()}
        onUseMyLocation={vi.fn()}
        locating={false}
        gpsError={null}
        language="en"
        onLanguageChange={vi.fn()}
        suggestedLanguage="hi"
        simulateStale={false}
        loading={false}
        canPromptInstall={false}
        isStandalone={false}
        onOpenInstallModal={vi.fn()}
      />
    );

    const trigger = screen.getByRole("button", {
      name: /Choose location or search Indian city/i
    });

    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Close location menu" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    const getAppBtn = screen.getByRole("button", { name: /Download or install PRANA-AI app/i });
    getAppBtn.focus();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).not.toHaveFocus();
  });
});
