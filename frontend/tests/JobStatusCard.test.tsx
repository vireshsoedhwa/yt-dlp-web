/**
 * Tests for JobStatusCard component.
 *
 * Tests: initial render, polling, status badge colors, error display, dismiss.
 * Uses vi.mock to mock the API client.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { JobInfo } from "../src/types";

// Mock the API client
vi.mock("../src/lib/api", () => ({
  getJobStatus: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { getJobStatus, ApiError } from "../src/lib/api";
import { JobStatusCard, formatCountdown } from "../src/components/JobStatusCard";

const mockGetJobStatus = vi.mocked(getJobStatus);

function makeJob(overrides: Partial<JobInfo> = {}): JobInfo {
  return {
    job_id: "abc123",
    status: "queued",
    result: null,
    error: null,
    enqueued_at: "2025-01-01T12:00:00",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockGetJobStatus.mockReset();
});

describe("JobStatusCard", () => {
  it("should show the URL being downloaded", () => {
    mockGetJobStatus.mockResolvedValue(makeJob());
    render(
      <JobStatusCard jobId="abc123" url="https://example.com/video" onDismiss={vi.fn()} />,
    );
    expect(
      screen.getByText("https://example.com/video"),
    ).toBeInTheDocument();
  });

  it("should display 'queued' status badge initially", () => {
    mockGetJobStatus.mockResolvedValue(makeJob({ status: "queued" }));
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("queued")).toBeInTheDocument();
  });

  it("should call getJobStatus with the job_id", async () => {
    mockGetJobStatus.mockResolvedValue(makeJob());
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(mockGetJobStatus).toHaveBeenCalledWith("abc123");
    });
  });

  it("should show 'finished' badge when job completes", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: { status: "completed", url: "https://example.com", format: "best" },
        ended_at: "2025-01-01T12:01:00",
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("finished")).toBeInTheDocument();
    });
  });

  it("test_card_shows_title_when_finished", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "137+140",
          files: [],
          title: "Test Video",
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Video")).toBeInTheDocument();
    });
  });

  it("test_card_shows_thumbnail_when_finished", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "best",
          files: [],
          title: "Test Video",
          thumbnail: "https://example.com/thumb.jpg",
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      const img = screen.getByRole("img");
      expect(img).toHaveAttribute("src", "https://example.com/thumb.jpg");
    });
  });

  it("test_card_shows_quality_label_not_raw_format", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "137+140",
          files: [],
          quality: "1080p",
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Quality: 1080p")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Format:/)).not.toBeInTheDocument();
  });

  it("test_card_shows_audio_label_for_audio_quality", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "bestaudio",
          files: [],
          quality: "audio",
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Audio only (MP3)")).toBeInTheDocument();
    });
  });

  it("test_card_shows_url_as_fallback_when_no_title", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "started",
        result: null,
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com/video" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("https://example.com/video")).toBeInTheDocument();
    });
    // No title text should be present (result is null so title is undefined)
    expect(screen.queryByText("Test Video")).not.toBeInTheDocument();
  });

  it("should show error message when job fails", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "failed",
        error: "ValueError: Bad URL",
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("ValueError: Bad URL")).toBeInTheDocument();
    });
  });

  it("should call onDismiss when dismiss button is clicked", async () => {
    mockGetJobStatus.mockResolvedValue(makeJob());
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={onDismiss} />,
    );

    await user.click(screen.getByLabelText("Dismiss job"));
    expect(onDismiss).toHaveBeenCalledWith("abc123");
  });

  it("should show polling indicator while job is active", async () => {
    mockGetJobStatus.mockResolvedValue(makeJob({ status: "started" }));
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("polling...")).toBeInTheDocument();
    });
  });

  it("should not show polling indicator when job is finished", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({ status: "finished", result: { status: "completed", url: "", format: "" } }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("finished")).toBeInTheDocument();
    });
    expect(screen.queryByText("polling...")).not.toBeInTheDocument();
  });

  it("should show download links when job is finished with files", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "best",
          files: ["Test Video [abc123].mp4"],
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Video [abc123].mp4")).toBeInTheDocument();
    });

    // Should be a button, not an <a> tag (buttons use fetch with session header)
    const btn = screen.getByText("Test Video [abc123].mp4").closest("button");
    expect(btn).not.toBeNull();
    expect(btn?.tagName).toBe("BUTTON");
  });

  it("should show multiple download links for multiple files", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: {
          status: "completed",
          url: "https://example.com",
          format: "bestvideo+bestaudio",
          files: ["video.mp4", "audio.webm"],
        },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("video.mp4")).toBeInTheDocument();
    });
    expect(screen.getByText("audio.webm")).toBeInTheDocument();
  });

  it("should show fallback message when finished but no files captured", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: { status: "completed", url: "https://example.com", format: "best", files: [] },
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("finished")).toBeInTheDocument();
    });
    expect(screen.getByText("Download complete (filename unavailable)")).toBeInTheDocument();
  });

  it("should not show download links when job is still in progress", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "started",
        result: null,
      }),
    );
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("started")).toBeInTheDocument();
    });
    expect(screen.queryByText("Download complete (filename unavailable)")).not.toBeInTheDocument();
  });

  it("should show poll error when getJobStatus fails", async () => {
    mockGetJobStatus.mockRejectedValue(new ApiError(500, "Connection error"));
    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Connection error")).toBeInTheDocument();
    });
  });

  it("should poll at the configured interval, not tight-loop", async () => {
    // Verify that getJobStatus is called once on mount, then once per interval.
    // With a 2s interval and fake timers, the second call should only
    // happen after advancing the timer by 2000ms.
    vi.useFakeTimers();
    mockGetJobStatus.mockResolvedValue(makeJob({ status: "started" }));

    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    // Flush the initial fetch on mount
    await vi.advanceTimersByTimeAsync(0);
    expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

    // Advance less than the interval — should NOT have polled again yet
    await vi.advanceTimersByTimeAsync(1999);
    expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

    // Advance past the interval — should have polled once more
    await vi.advanceTimersByTimeAsync(1);
    expect(mockGetJobStatus).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it("should stop polling when job reaches finished state", async () => {
    vi.useFakeTimers();
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        result: { status: "completed", url: "https://example.com", format: "best" },
      }),
    );

    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    // Initial fetch on mount
    await vi.advanceTimersByTimeAsync(0);
    expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

    // Advance past the interval — should NOT poll again since job is finished
    await vi.advanceTimersByTimeAsync(3000);
    expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it("test_formatCountdown_formats_correctly", () => {
    expect(formatCountdown(3661000)).toBe("1:01:01");
    expect(formatCountdown(0)).toBe("0:00:00");
    expect(formatCountdown(7322000)).toBe("2:02:02");
  });

  it("test_countdown_displayed_when_finished", async () => {
    const now = new Date();
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        ended_at: now.toISOString(),
        result: { status: "completed", url: "https://example.com", format: "best" },
      }),
    );

    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Expires in/)).toBeInTheDocument();
    });
  });

  it("test_countdown_not_displayed_while_downloading", async () => {
    mockGetJobStatus.mockResolvedValue(
      makeJob({ status: "started", ended_at: null }),
    );

    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("started")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Expires in/)).not.toBeInTheDocument();
  });

  it("test_countdown_calls_onDismiss_at_zero", async () => {
    // ended_at 3 hours ago → already expired past the 2-hour TTL
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    const onDismiss = vi.fn();
    mockGetJobStatus.mockResolvedValue(
      makeJob({
        status: "finished",
        ended_at: threeHoursAgo,
        result: { status: "completed", url: "https://example.com", format: "best" },
      }),
    );

    render(
      <JobStatusCard jobId="abc123" url="https://example.com" onDismiss={onDismiss} />,
    );

    await waitFor(() => {
      expect(onDismiss).toHaveBeenCalledWith("abc123");
    });
  });
});