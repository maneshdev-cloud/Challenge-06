import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATEGORY_TEMPLATES, FALLBACK_CITIES } from "../data/constants";
import {
  clearSavedHousehold,
  createInitialPlanState,
  INITIAL_CHAT_MESSAGES,
  loadSavedHousehold,
  planReducer,
  saveHousehold
} from "../hooks/planReducer";
import usePranaPlan from "../hooks/usePranaPlan";
import {
  detectPlatform,
  formatTextForSpeech,
  queryPermissionState,
  requestCameraAccess,
  requestMicrophoneAccess
} from "../utils/pwaAndPermissions";

const mockFetchPresets = vi.fn();
const mockFetchCities = vi.fn();
const mockGeneratePlan = vi.fn();
const mockReverseGeocode = vi.fn();

vi.mock("../api/client", () => ({
  fetchPresets: (...args) => mockFetchPresets(...args),
  fetchCities: (...args) => mockFetchCities(...args),
  generatePlan: (...args) => mockGeneratePlan(...args),
  reverseGeocode: (...args) => mockReverseGeocode(...args)
}));

describe("planReducer and household persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("handles boot, category selection, toggle stale, and chat functional updates", () => {
    const initial = createInitialPlanState(FALLBACK_CITIES);
    expect(initial.loading).toBe(true);
    expect(initial.chatMessages).toEqual(INITIAL_CHAT_MESSAGES);

    const cfg = { ...CATEGORY_TEMPLATES.adults_commuters, city: "pune" };
    const booted = planReducer(initial, {
      type: "BOOT_LOADED",
      citiesData: FALLBACK_CITIES,
      presetsList: [{ id: "mumbai_family", name: "Mumbai" }],
      initialCategory: "adults_commuters",
      initialConfig: cfg
    });
    expect(booted.planConfig.city).toBe("pune");
    expect(booted.presets).toHaveLength(1);

    const toggled = planReducer(booted, { type: "TOGGLE_STALE", simulateStale: true });
    expect(toggled.simulateStale).toBe(true);

    const chatted = planReducer(toggled, {
      type: "SET_CHAT_MESSAGES",
      value: (prev) => [...prev, { role: "user", text: "When should I walk?" }]
    });
    expect(chatted.chatMessages).toHaveLength(2);
    expect(chatted.chatMessages[1].text).toBe("When should I walk?");
  });

  it("persists and clears household settings safely in localStorage", () => {
    const cfg = { ...CATEGORY_TEMPLATES.seniors, city: "delhi", language: "hi" };
    saveHousehold(cfg);
    expect(loadSavedHousehold()?.city).toBe("delhi");
    expect(loadSavedHousehold()?.language).toBe("hi");

    clearSavedHousehold();
    expect(loadSavedHousehold()).toBeNull();
  });
});

describe("usePranaPlan hook lifecycle", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetchPresets.mockResolvedValue([{ id: "mumbai_family", city: "mumbai", members: [], activities: [] }]);
    mockFetchCities.mockResolvedValue(FALLBACK_CITIES);
    mockGeneratePlan.mockResolvedValue({
      evidence_bundle: {
        emergency_alert: false,
        air_snapshot: { current_naqi: 130 }
      },
      narrative: "Cleanest window is 1:00 PM - 3:00 PM."
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads presets/cities on mount, runs initial plan, and updates document lang on switch", async () => {
    const { result } = renderHook(() => usePranaPlan());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.planConfig.city).toBe("mumbai");
    expect(mockGeneratePlan).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.handleLanguageChange("hi");
    });

    await waitFor(() => expect(document.documentElement.lang).toBe("hi"));
    expect(result.current.planConfig.language).toBe("hi");
  });
});

describe("pwaAndPermissions utilities", () => {
  it("normalizes pollutants and units cleanly for Indian TTS playback", () => {
    const clean = formatTextForSpeech("**PM2.5** is 85 ug/m3 and CO2e saved is 2 kg\n- Wear N95");
    expect(clean).toBe("P M 2.5 is 85 micrograms per cubic meter and C O 2 saved is 2 kg. Wear N95");
  });

  it("detects platform flags and handles permission requests gracefully", async () => {
    const platform = detectPlatform();
    expect(typeof platform.isMobile).toBe("boolean");

    vi.stubGlobal("isSecureContext", true);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(Object.assign(new Error("Denied"), { name: "NotAllowedError" }))
      }
    });
    const micRes = await requestMicrophoneAccess();
    const camRes = await requestCameraAccess();
    expect(micRes.state).toBe("denied");
    expect(camRes.state).toBe("denied");

    const geoState = await queryPermissionState("geolocation");
    expect(["granted", "prompt", "denied", "unsupported"]).toContain(geoState);
    vi.unstubAllGlobals();
  });
});
