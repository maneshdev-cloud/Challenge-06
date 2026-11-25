import { afterEach, describe, expect, it, vi } from "vitest";
import { auditRoomPhoto, generatePlan, sendChatQuestion } from "../api/client";

describe("API client resilience", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("auditRoomPhoto reads response body once for JSON and plain-text errors", async () => {
    const textFn = vi.fn().mockResolvedValue(JSON.stringify({ detail: "File exceeds 5 MB" }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 413,
        text: textFn
      })
    );

    const file = new File(["dummy"], "room.jpg", { type: "image/jpeg" });
    await expect(
      auditRoomPhoto(file, { city: "mumbai", language: "en", current_naqi: 120 })
    ).rejects.toThrow("File exceeds 5 MB");
    expect(textFn).toHaveBeenCalledTimes(1);

    const plainTextFn = vi.fn().mockResolvedValue("Bad Gateway");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        text: plainTextFn
      })
    );

    await expect(
      auditRoomPhoto(file, { city: "delhi", language: "en", current_naqi: 240 })
    ).rejects.toThrow("Bad Gateway");
    expect(plainTextFn).toHaveBeenCalledTimes(1);
  });

  it("generatePlan respects external AbortSignal without retrying", async () => {
    const controller = new AbortController();
    controller.abort();

    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await expect(
      generatePlan({ city: "delhi" }, { signal: controller.signal })
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sendChatQuestion forwards evidence_signature in POST /v1/chat body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        reply: "Walk at 2 PM.",
        emergency_alert: false,
        emergency_message: null,
        source: "deterministic_template",
        validator_passed: true
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    await sendChatQuestion("Can I walk?", { app_name: "PRANA-AI" }, "en", "sig-abc-123");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/chat$/);
    expect(JSON.parse(init.body)).toEqual({
      message: "Can I walk?",
      evidence_bundle: { app_name: "PRANA-AI" },
      evidence_signature: "sig-abc-123",
      language: "en"
    });
  });
});
