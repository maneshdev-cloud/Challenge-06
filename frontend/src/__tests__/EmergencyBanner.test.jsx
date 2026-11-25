import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import EmergencyBanner from "../components/EmergencyBanner";

describe("EmergencyBanner", () => {
  it("renders nothing when message is empty", () => {
    const { container } = render(<EmergencyBanner message={null} onDismiss={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders accessible alert with tel:108/112 links and dismisses cleanly", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();

    render(
      <EmergencyBanner
        message="Seek urgent emergency evaluation immediately."
        onDismiss={onDismiss}
      />
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /Urgent Medical Triage/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "108" })).toHaveAttribute("href", "tel:108");
    expect(screen.getByRole("link", { name: "112" })).toHaveAttribute("href", "tel:112");

    await user.click(screen.getByRole("button", { name: /Dismiss emergency banner/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
