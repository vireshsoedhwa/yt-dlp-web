/**
 * Tests for UrlInput component.
 *
 * Tests: form submission, empty input prevention, loading state, placeholder.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UrlInput } from "../src/components/UrlInput";

describe("UrlInput", () => {
  it("should call onSubmit with the trimmed URL when submitted", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<UrlInput onSubmit={onSubmit} />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "  https://example.com/video  ",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    expect(onSubmit).toHaveBeenCalledWith("https://example.com/video");
  });

  it("should not call onSubmit when input is empty", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<UrlInput onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("should not call onSubmit when input is whitespace only", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<UrlInput onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Video URL"), "   ");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("should disable input and button when loading=true", () => {
    render(<UrlInput onSubmit={vi.fn()} loading={true} />);

    expect(screen.getByLabelText("Video URL")).toBeDisabled();
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("should show 'Loading...' text when loading", () => {
    render(<UrlInput onSubmit={vi.fn()} loading={true} />);

    expect(screen.getByRole("button")).toHaveTextContent("Loading...");
  });

  it("should show custom placeholder when provided", () => {
    render(<UrlInput onSubmit={vi.fn()} placeholder="Enter URL here" />);

    expect(screen.getByLabelText("Video URL")).toHaveAttribute(
      "placeholder",
      "Enter URL here",
    );
  });

  it("should submit on Enter key", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<UrlInput onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Video URL");
    await user.type(input, "https://example.com/video");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("https://example.com/video");
  });
});