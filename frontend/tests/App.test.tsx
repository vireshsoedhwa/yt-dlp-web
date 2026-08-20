/**
 * Tests for App component — integration-level tests.
 *
 * Mocks the API client to test the full flow:
 * URL input -> fetch info -> show card -> download -> show job status.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { VideoInfo, DownloadResponse, JobInfo } from "../src/types";

// Mock the API client
vi.mock("../src/lib/api", () => ({
  fetchVideoInfo: vi.fn(),
  startDownload: vi.fn(),
  getJobStatus: vi.fn(),
  getJobs: vi.fn(),
  dismissJob: vi.fn(),
  downloadFile: vi.fn(),
  listFiles: vi.fn(),
  getOrCreateSessionId: vi.fn(() => "test-session-id"),
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

import { App } from "../src/App";
import { fetchVideoInfo, startDownload, getJobStatus, getJobs, dismissJob, ApiError } from "../src/lib/api";

const mockFetchVideoInfo = vi.mocked(fetchVideoInfo);
const mockStartDownload = vi.mocked(startDownload);
const mockGetJobStatus = vi.mocked(getJobStatus);
const mockGetJobs = vi.mocked(getJobs);
const mockDismissJob = vi.mocked(dismissJob);

const mockInfo: VideoInfo = {
  title: "Test Video",
  uploader: "Test Channel",
  duration: 120,
  thumbnail: null,
  formats: [{ format_id: "137", ext: "mp4", resolution: "1080p" }],
};

const mockDownloadResponse: DownloadResponse = {
  job_id: "job1",
  status: "queued",
  message: "Download job enqueued.",
};

const mockJobFinished: JobInfo = {
  job_id: "job1",
  status: "finished",
  result: { status: "finished", url: "https://example.com/video", format: "best", files: ["video.mp4"] },
  error: null,
  enqueued_at: null,
  started_at: null,
  ended_at: null,
};

const mockJobFailed: JobInfo = {
  job_id: "job1",
  status: "failed",
  result: null,
  error: "Download failed",
  enqueued_at: null,
  started_at: null,
  ended_at: null,
};

function makeApiError(status: number, message: string): ApiError {
  return new ApiError(status, message);
}

beforeEach(() => {
  mockFetchVideoInfo.mockReset();
  mockStartDownload.mockReset();
  mockGetJobStatus.mockReset();
  mockGetJobs.mockReset();
  mockDismissJob.mockReset();
  // Default: job is already finished so polling exits immediately
  mockGetJobStatus.mockResolvedValue(mockJobFinished);
  // Default: no restored jobs
  mockGetJobs.mockResolvedValue([]);
});

describe("App", () => {
  it("should render the title 'yt-dlp Web'", () => {
    render(<App />);
    expect(screen.getByText("yt-dlp Web")).toBeInTheDocument();
  });

  it("should show video info after entering URL and submitting", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/video",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Test Video")).toBeInTheDocument();
    });
  });

  it("should show error message when fetchVideoInfo fails", async () => {
    mockFetchVideoInfo.mockRejectedValue(makeApiError(400, "Video not found"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/bad",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Video not found")).toBeInTheDocument();
    });
  });

  it("should show generic error when fetchVideoInfo throws non-ApiError", async () => {
    mockFetchVideoInfo.mockRejectedValue(new Error("Network failure"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/bad",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Failed to fetch video info")).toBeInTheDocument();
    });
  });

  it("should add a job status card after clicking Download", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockResolvedValue(mockDownloadResponse);
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/video",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Test Video")).toBeInTheDocument();
    });

    // Click download
    await user.click(screen.getByRole("button", { name: /^download$/i }));

    await waitFor(() => {
      expect(screen.getByText("Downloads")).toBeInTheDocument();
    });
    expect(
      screen.getByText("https://example.com/video"),
    ).toBeInTheDocument();
  });

  it("should keep download button disabled while job is still running", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockResolvedValue(mockDownloadResponse);
    // Job stays "started" — never finishes
    mockGetJobStatus.mockResolvedValue({ ...mockJobFinished, status: "started" });
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(screen.getByLabelText("Video URL"), "https://example.com/video");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));
    await waitFor(() => expect(screen.getByText("Test Video")).toBeInTheDocument());

    // Click download — button enters downloading state
    await user.click(screen.getByRole("button", { name: /^download$/i }));

    // Wait for button to show "Downloading..." with spinner
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /downloading/i })).toBeDisabled();
    });
  });

  it("should re-enable download button after job finishes", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockResolvedValue(mockDownloadResponse);
    // Job is finished immediately
    mockGetJobStatus.mockResolvedValue(mockJobFinished);
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(screen.getByLabelText("Video URL"), "https://example.com/video");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));
    await waitFor(() => expect(screen.getByText("Test Video")).toBeInTheDocument());

    // Click download
    await user.click(screen.getByRole("button", { name: /^download$/i }));

    // After polling sees "finished", button re-enables
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^download$/i })).toBeEnabled();
    });
  });

  it("should re-enable download button after job fails", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockResolvedValue(mockDownloadResponse);
    mockGetJobStatus.mockResolvedValue(mockJobFailed);
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(screen.getByLabelText("Video URL"), "https://example.com/video");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));
    await waitFor(() => expect(screen.getByText("Test Video")).toBeInTheDocument());

    // Click download
    await user.click(screen.getByRole("button", { name: /^download$/i }));

    // After polling sees "failed", button re-enables
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^download$/i })).toBeEnabled();
    });
  });

  it("should not call startDownload twice when download button is double-clicked", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockResolvedValue(mockDownloadResponse);
    mockGetJobStatus.mockResolvedValue({ ...mockJobFinished, status: "started" });
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(screen.getByLabelText("Video URL"), "https://example.com/video");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));
    await waitFor(() => expect(screen.getByText("Test Video")).toBeInTheDocument());

    // Double-click the download button
    const dlBtn = screen.getByRole("button", { name: /^download$/i });
    await user.click(dlBtn);
    await user.click(dlBtn);

    // Only one startDownload call should have been made
    await waitFor(() => {
      expect(mockStartDownload).toHaveBeenCalledTimes(1);
    });
  });

  it("should replace old job card when re-downloading the same URL", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    // First download: job1 finishes immediately
    mockStartDownload.mockResolvedValueOnce({ ...mockDownloadResponse, job_id: "job1" });
    mockGetJobStatus.mockResolvedValueOnce(mockJobFinished);
    // Second download: job2 (new job from backend)
    mockStartDownload.mockResolvedValueOnce({ ...mockDownloadResponse, job_id: "job2" });
    const user = userEvent.setup();
    render(<App />);

    // Fetch info
    await user.type(screen.getByLabelText("Video URL"), "https://example.com/video");
    await user.click(screen.getByRole("button", { name: /fetch info/i }));
    await waitFor(() => expect(screen.getByText("Test Video")).toBeInTheDocument());

    // First download
    await user.click(screen.getByRole("button", { name: /^download$/i }));
    await waitFor(() => {
      expect(screen.getByText("https://example.com/video")).toBeInTheDocument();
    });

    // Wait for button to re-enable (job1 finished)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^download$/i })).toBeEnabled();
    });

    // Second download — should replace job1 card, not add a second one
    await user.click(screen.getByRole("button", { name: /^download$/i }));
    await waitFor(() => {
      expect(mockStartDownload).toHaveBeenCalledTimes(2);
    });

    // Should only have one job card (one URL shown, not duplicated)
    const urlElements = screen.getAllByText("https://example.com/video");
    expect(urlElements).toHaveLength(1);
  });

  it("should show error when startDownload fails with ApiError", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockRejectedValue(makeApiError(500, "Download failed"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/video",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Test Video")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /^download$/i }));

    await waitFor(() => {
      expect(screen.getByText("Download failed")).toBeInTheDocument();
    });
  });

  it("should show generic error when startDownload throws non-ApiError", async () => {
    mockFetchVideoInfo.mockResolvedValue(mockInfo);
    mockStartDownload.mockRejectedValue(new Error("Network failure"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/video",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Test Video")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /^download$/i }));

    await waitFor(() => {
      expect(screen.getByText("Failed to start download")).toBeInTheDocument();
    });
  });

  it("should dismiss error when dismiss button is clicked", async () => {
    mockFetchVideoInfo.mockRejectedValue(makeApiError(400, "Error message"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByLabelText("Video URL"),
      "https://example.com/bad",
    );
    await user.click(screen.getByRole("button", { name: /fetch info/i }));

    await waitFor(() => {
      expect(screen.getByText("Error message")).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Dismiss error"));

    await waitFor(() => {
      expect(screen.queryByText("Error message")).not.toBeInTheDocument();
    });
  });

  it("should show 'Powered by yt-dlp' footer link", () => {
    render(<App />);
    const link = screen.getByText("yt-dlp");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "https://github.com/yt-dlp/yt-dlp");
  });

  it("test_restores_jobs_on_mount", async () => {
    mockGetJobs.mockResolvedValue([
      { job_id: "job1", url: "https://example.com/video", status: "finished", result: null, error: null },
    ]);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("https://example.com/video")).toBeInTheDocument();
    });
  });

  it("test_dismiss_job_calls_backend", async () => {
    mockGetJobs.mockResolvedValue([
      { job_id: "job1", url: "https://example.com/video", status: "finished", result: null, error: null },
    ]);
    mockDismissJob.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<App />);

    // Wait for restored job to appear
    await waitFor(() => {
      expect(screen.getByText("https://example.com/video")).toBeInTheDocument();
    });

    // Click dismiss button
    await user.click(screen.getByLabelText("Dismiss job"));

    await waitFor(() => {
      expect(mockDismissJob).toHaveBeenCalledWith("job1");
    });
  });

  it("test_restored_jobs_show_correct_url", async () => {
    mockGetJobs.mockResolvedValue([
      { job_id: "job42", url: "https://example.com/specific-url", status: "finished", result: null, error: null },
    ]);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("https://example.com/specific-url")).toBeInTheDocument();
    });
  });
});