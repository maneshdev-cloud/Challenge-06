import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RoomAuditCard from "../components/RoomAuditCard";

const mockAuditRoomPhoto = vi.fn();

vi.mock("../api/client", () => ({
  auditRoomPhoto: (...args) => mockAuditRoomPhoto(...args)
}));

describe("RoomAuditCard", () => {
  beforeEach(() => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:mock-room-photo")
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn()
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("rejects non-image uploads and oversized >5MB photos with accessible role=alert errors", async () => {
    const user = userEvent.setup({ applyAccept: false });
    vi.stubGlobal(
      "Image",
      class MockImage {
        set src(_) {
          queueMicrotask(() => this.onerror?.());
        }
      }
    );

    render(<RoomAuditCard city="delhi" areaName="Dwarka" language="en" currentNaqi={285} />);

    const galleryInput = screen.getByLabelText("Upload room or kitchen photo from device");
    const badFile = new File(["plain text"], "notes.txt", { type: "text/plain" });
    await user.upload(galleryInput, badFile);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Please choose a JPG, PNG, or WebP photo/i
    );

    const bigImage = new File(["bytes"], "huge.jpg", { type: "image/jpeg" });
    Object.defineProperty(bigImage, "size", { value: 6 * 1024 * 1024 });
    await user.upload(galleryInput, bigImage);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Photo exceeds 5 MB/i)
    );
    expect(mockAuditRoomPhoto).not.toHaveBeenCalled();
  });

  it("uploads valid room image, displays Rs 0-500 tips, and handles API errors", async () => {
    const user = userEvent.setup();
    mockAuditRoomPhoto.mockResolvedValueOnce({
      source: "gemini",
      room_summary: "Unsealed window sill facing road.",
      tips: [
        {
          title: "Seal bottom door gap",
          cost_inr: "Rs. 0",
          action: "Place a folded damp towel under street-facing door.",
          why_it_helps: "Blocks cold traffic PM2.5 drift."
        }
      ],
      disclaimer: "Visual proxy only."
    });

    render(
      <RoomAuditCard
        city="mumbai"
        areaName="Andheri"
        language="en"
        currentNaqi={142}
        onOpenPermissions={vi.fn()}
      />
    );

    const galleryInput = screen.getByLabelText("Upload room or kitchen photo from device");
    const validPng = new File(["pngbytes"], "room.png", { type: "image/png" });
    await user.upload(galleryInput, validPng);

    await waitFor(() =>
      expect(screen.getByText("Unsealed window sill facing road.")).toBeInTheDocument()
    );
    expect(screen.getByText("Gemini Vision")).toBeInTheDocument();
    expect(screen.getByText("Seal bottom door gap")).toBeInTheDocument();
    expect(screen.getByText("Rs. 0")).toBeInTheDocument();
    expect(screen.getByAltText("Uploaded room preview")).toHaveAttribute(
      "src",
      "blob:mock-room-photo"
    );

    mockAuditRoomPhoto.mockRejectedValueOnce(new Error("Vision backend unavailable"));
    await user.upload(galleryInput, validPng);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Vision backend unavailable")
    );
  });
});
