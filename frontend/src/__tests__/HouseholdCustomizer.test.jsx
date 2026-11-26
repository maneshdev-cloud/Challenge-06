import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import HouseholdCustomizer from "../components/HouseholdCustomizer";

const SAMPLE_CONFIG = {
  city: "delhi",
  budget_tier: "under_500",
  uses_agarbatti_or_coils: false,
  dry_sweeps: true,
  members: [
    { name: "Dadi", age: 68, conditions: ["elderly"] },
    { name: "Rohan", age: 30, conditions: ["adult"] }
  ],
  activities: [
    {
      id: "act_walk",
      name: "Morning Walk",
      member_name: "Dadi",
      flexibility: "flexible",
      planned_hour: 7,
      duration_min: 30,
      activity_level: "elderly_walk",
      current_mask: "none",
      is_commute: false,
      is_work_shift: false
    },
    {
      id: "act_work",
      name: "Office Commute",
      member_name: "Rohan",
      flexibility: "fixed",
      planned_hour: 9,
      duration_min: 45,
      activity_level: "seated",
      current_mask: "none",
      is_commute: true,
      is_work_shift: false
    }
  ]
};

describe("HouseholdCustomizer", () => {
  it("allows adding an infant with age 0 without coercing 0 to 25", async () => {
    const user = userEvent.setup();
    const onUpdateConfig = vi.fn();

    render(
      <HouseholdCustomizer
        open
        onClose={vi.fn()}
        planConfig={SAMPLE_CONFIG}
        onUpdateConfig={onUpdateConfig}
        onResetSaved={vi.fn()}
        saving={false}
      />
    );

    await user.type(screen.getByLabelText("New member name"), "Aarav");
    const ageInput = screen.getByLabelText("New member age");
    await user.clear(ageInput);
    await user.type(ageInput, "0");

    const addButtons = screen.getAllByRole("button", { name: /^add$/i });
    await user.click(addButtons[0]);

    expect(onUpdateConfig).toHaveBeenCalledTimes(1);
    const updated = onUpdateConfig.mock.calls[0][0];
    expect(updated.members).toHaveLength(3);
    expect(updated.members[2]).toMatchObject({ name: "Aarav", age: 0 });

    await user.type(screen.getByLabelText("New member name"), "Dada");
    await user.clear(ageInput);
    await user.type(ageInput, "1e2");
    await user.click(addButtons[0]);
    expect(onUpdateConfig.mock.calls[1][0].members[2]).toMatchObject({ name: "Dada", age: 100 });
  });

  it("toggles indoor habits, reassigns tasks when removing a member, and triggers reset", async () => {
    const user = userEvent.setup();
    const onUpdateConfig = vi.fn();
    const onResetSaved = vi.fn();

    render(
      <HouseholdCustomizer
        open
        onClose={vi.fn()}
        planConfig={SAMPLE_CONFIG}
        onUpdateConfig={onUpdateConfig}
        onResetSaved={onResetSaved}
        saving={false}
      />
    );

    const agarbattiCheckbox = screen.getByLabelText(/Uses agarbatti, dhoop/i);
    expect(agarbattiCheckbox).toHaveClass("focus-visible:ring-2");
    await user.click(agarbattiCheckbox);
    expect(onUpdateConfig.mock.calls[0][0].uses_agarbatti_or_coils).toBe(true);

    await user.click(screen.getByRole("button", { name: "Remove Dadi" }));
    const afterRemove = onUpdateConfig.mock.calls[1][0];
    expect(afterRemove.members.map((m) => m.name)).toEqual(["Rohan"]);
    expect(afterRemove.activities[0].member_name).toBe("Rohan");

    await user.click(screen.getByRole("button", { name: /Reset Saved Household/i }));
    expect(onResetSaved).toHaveBeenCalledTimes(1);
  });
});
