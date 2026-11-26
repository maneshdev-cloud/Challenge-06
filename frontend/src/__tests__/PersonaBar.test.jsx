import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PersonaBar from "../components/PersonaBar";

const PRESETS = [
  { id: "delhi_family", label: "Delhi Household", short_tag: "Winter smog demo" },
  { id: "delivery_rider", label: "2W Delivery Rider", short_tag: "8h road shift" }
];

describe("PersonaBar", () => {
  it("tracks aria-pressed category state and opens accessible preset menu", async () => {
    const user = userEvent.setup();
    const onSelectCategory = vi.fn();
    const onSelectPreset = vi.fn();
    const onOpenCustomizer = vi.fn();

    render(
      <PersonaBar
        activeCategoryId="adults_commuters"
        onSelectCategory={onSelectCategory}
        presets={PRESETS}
        activePresetId={null}
        onSelectPreset={onSelectPreset}
        onOpenCustomizer={onOpenCustomizer}
      />
    );

    const adultsBtn = screen.getByRole("button", { name: "Adults & Commuters" });
    const seniorsBtn = screen.getByRole("button", { name: "Seniors" });
    expect(adultsBtn).toHaveAttribute("aria-pressed", "true");
    expect(seniorsBtn).toHaveAttribute("aria-pressed", "false");

    await user.click(seniorsBtn);
    expect(onSelectCategory).toHaveBeenCalledWith("seniors");

    const presetBtn = screen.getByRole("button", { name: /Quick Demo Presets/i });
    expect(presetBtn).toHaveAttribute("aria-expanded", "false");

    await user.click(presetBtn);
    expect(presetBtn).toHaveAttribute("aria-expanded", "true");

    const menu = screen.getByRole("menu", { name: /1-Click Benchmark Personas/i });
    expect(menu.className).toContain("left-0");
    expect(menu.className).toContain("sm:right-0");
    expect(menu.className).toContain("sm:left-auto");

    await user.click(screen.getByRole("menuitem", { name: /Delhi Household/i }));
    expect(onSelectPreset).toHaveBeenCalledWith(PRESETS[0]);
    expect(presetBtn).toHaveAttribute("aria-expanded", "false");
  });
});
