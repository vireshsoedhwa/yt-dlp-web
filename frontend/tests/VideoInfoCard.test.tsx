/**
 * Tests for VideoInfoCard component and formatDuration helper.
 *
 * Tests: rendering metadata, audio-only toggle, format input, download callback,
 * formatDuration edge cases.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  VideoInfoCard,
  formatDuration,
} from "../src/components/VideoInfoCard";
import type { VideoInfo } from "../src/types";

const mockInfo: VideoInfo = {
  title: "Test Video",
  uploader: "Test Channel",
  duration: 125,
  thumbnail: "https://example.com/thumb.jpg",
  formats: [
    { format_id: "137", ext: "mp4", resolution: "1080p" },
    { format_id: "251", ext: "webm", resolution: "audio only" },
  ],
};

describe("formatDuration", () => {
  it("should format seconds as M:SS", () => {
    expect(formatDuration(125)).toBe("2:05");
  });

  it("should handle exactly 0 seconds", () => {
    expect(formatDuration(0)).toBe("0:00");
  });

  it("should pad seconds with leading zero", () => {
    expect(formatDuration(65)).toBe("1:05");
  });

  it("should handle large durations", () => {
    expect(formatDuration(3661)).toBe("61:01");
  });
});

describe("VideoInfoCard", () => {
  it("should display the video title", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);
    expect(screen.getByText("Test Video")).toBeInTheDocument();
  });

  it("should display the uploader", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);
    expect(screen.getByText("Test Channel")).toBeInTheDocument();
  });

  it("should display the formatted duration", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);
    expect(screen.getByText("Duration: 2:05")).toBeInTheDocument();
  });

  it("should display the format count", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);
    expect(screen.getByText("2 formats available")).toBeInTheDocument();
  });

  it("should render the thumbnail image", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);
    const img = screen.getByAltText("Test Video");
    expect(img).toHaveAttribute("src", "https://example.com/thumb.jpg");
  });

  it("should not render thumbnail when null", () => {
    const noThumb = { ...mockInfo, thumbnail: null };
    render(<VideoInfoCard info={noThumb} onDownload={vi.fn()} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("should call onDownload with video format when Download clicked", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(<VideoInfoCard info={mockInfo} onDownload={onDownload} />);

    await user.click(screen.getByRole("button", { name: /download/i }));

    expect(onDownload).toHaveBeenCalledWith({
      format: "bestvideo+bestaudio/best",
      audio_only: false,
    });
  });

  it("should call onDownload with audio format when audio-only is checked", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(<VideoInfoCard info={mockInfo} onDownload={onDownload} />);

    await user.click(screen.getByLabelText(/audio only/i));
    await user.click(screen.getByRole("button", { name: /download/i }));

    expect(onDownload).toHaveBeenCalledWith({
      format: "bestaudio/best",
      audio_only: true,
    });
  });

  it("should hide format input when audio-only is checked", async () => {
    const user = userEvent.setup();
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} />);

    // Format input visible initially
    expect(
      screen.getByPlaceholderText(/bestvideo\+bestaudio/i),
    ).toBeInTheDocument();

    // Check audio-only
    await user.click(screen.getByLabelText(/audio only/i));

    // Format input should be gone
    expect(
      screen.queryByPlaceholderText(/bestvideo\+bestaudio/i),
    ).not.toBeInTheDocument();
  });

  it("should show 'Downloading...' with spinner and be disabled when downloading=true", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} downloading />);
    const button = screen.getByRole("button", { name: /downloading/i });
    expect(button).toBeDisabled();
    // Spinner SVG is present
    expect(button.querySelector("svg")).toBeInTheDocument();
  });

  it("should not render uploader when null", () => {
    const noUploader = { ...mockInfo, uploader: null };
    render(<VideoInfoCard info={noUploader} onDownload={vi.fn()} />);
    expect(screen.queryByText("Test Channel")).not.toBeInTheDocument();
  });

  it("should not render duration when null", () => {
    const noDuration = { ...mockInfo, duration: null };
    render(<VideoInfoCard info={noDuration} onDownload={vi.fn()} />);
    expect(screen.queryByText(/Duration:/i)).not.toBeInTheDocument();
  });
});

describe("VideoInfoCard click lock", () => {
  it("should only call onDownload once when button is double-clicked rapidly", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(<VideoInfoCard info={mockInfo} onDownload={onDownload} />);

    const button = screen.getByRole("button", { name: /download/i });

    await user.click(button);
    await user.click(button);

    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("should not call onDownload on second click before downloading prop changes", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(<VideoInfoCard info={mockInfo} onDownload={onDownload} />);

    const button = screen.getByRole("button", { name: /download/i });

    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);

    // Second click should be blocked by clickLock
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("should reset click lock when downloading prop goes from true to false", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={false} />,
    );

    const button = screen.getByRole("button", { name: /download/i });

    // First click — locks and fires onDownload
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);

    // Second click — still locked (downloading hasn't changed)
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);

    // Parent sets downloading=true (job in progress)
    rerender(<VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={true} />);
    // Parent sets downloading=false (job done) -> useEffect resets clickLock
    rerender(<VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={false} />);

    // Now user can click again
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(2);
  });

  it("should show spinner and be disabled when downloading=true (click lock section)", () => {
    render(<VideoInfoCard info={mockInfo} onDownload={vi.fn()} downloading />);
    const button = screen.getByRole("button", { name: /downloading/i });
    expect(button).toBeDisabled();
    expect(button.querySelector("svg")).toBeInTheDocument();
  });

  it("should not reset click lock while downloading is still true", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={false} />,
    );

    const button = screen.getByRole("button", { name: /download/i });

    // First click locks
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(1);

    // Parent sets downloading=true (but not false yet)
    rerender(<VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={true} />);

    // Still locked — downloading went true, useEffect condition (!downloading) is false, no reset
    // Re-render with downloading=true again (no change, no effect re-run)
    // But the lock should still be active
    rerender(<VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={true} />);

    // Now set downloading=false -> lock resets
    rerender(<VideoInfoCard info={mockInfo} onDownload={onDownload} downloading={false} />);

    // Can click again
    await user.click(button);
    expect(onDownload).toHaveBeenCalledTimes(2);
  });
});