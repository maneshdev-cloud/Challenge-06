import { describe, expect, it } from "vitest";
import {
  formatHour,
  formatHourAmPm,
  formatTimeIst,
  getNaqiStyle
} from "../utils/formatters";

describe("formatters", () => {
  it("formats 24-hour and 12-hour labels including wrap-around", () => {
    expect(formatHour(0)).toBe("00:00");
    expect(formatHour(9)).toBe("09:00");
    expect(formatHour(25)).toBe("01:00");
    expect(formatHour(null)).toBe("--:--");
    expect(formatHour("abc")).toBe("--:--");

    expect(formatHourAmPm(0)).toBe("12:00 AM");
    expect(formatHourAmPm(8)).toBe("8:00 AM");
    expect(formatHourAmPm(12)).toBe("12:00 PM");
    expect(formatHourAmPm(17)).toBe("5:00 PM");
    expect(formatHourAmPm(undefined)).toBe("--");
    expect(formatHourAmPm("bad")).toBe("--");
  });

  it("maps CPCB NAQI categories to expected Tailwind badge styles", () => {
    expect(getNaqiStyle("Good").text).toContain("emerald");
    expect(getNaqiStyle("Moderate").text).toContain("amber");
    expect(getNaqiStyle("Poor").text).toContain("orange");
    expect(getNaqiStyle("Severe").text).toContain("red");
  });

  it("formats ISO timestamps in Asia/Kolkata", () => {
    const out = formatTimeIst("2026-11-25T06:30:00Z");
    expect(out).toMatch(/12:00/);
    expect(formatTimeIst("")).toBe("");
  });
});
