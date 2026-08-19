/**
 * Tests for src/lib/api.ts — API client functions.
 *
 * Mocks global fetch so no network calls are made.
 * Tests: fetchVideoInfo, startDownload, getJobStatus, listFiles, session management, extractError, ApiError.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fetchVideoInfo,
  startDownload,
  getJobStatus,
  listFiles,
  getOrCreateSessionId,
  ApiError,
} from "../src/lib/api";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
vi.stubGlobal("localStorage", localStorageMock);

// Mock crypto.randomUUID
vi.stubGlobal("crypto", {
  randomUUID: vi.fn(() => "test-uuid-1234-5678"),
});

beforeEach(() => {
  mockFetch.mockReset();
  localStorageMock.clear();
  vi.mocked(localStorageMock.getItem).mockClear();
  vi.mocked(localStorageMock.setItem).mockClear();
  vi.mocked(crypto.randomUUID).mockClear();
});

describe("fetchVideoInfo", () => {
  it("should return parsed VideoInfo on 200", async () => {
    const mockInfo = {
      title: "Test Video",
      uploader: "Test Channel",
      duration: 120,
      thumbnail: "https://example.com/thumb.jpg",
      formats: [{ format_id: "137", ext: "mp4", resolution: "1080p" }],
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockInfo,
    });

    const result = await fetchVideoInfo("https://example.com/video");

    expect(result.title).toBe("Test Video");
    expect(result.uploader).toBe("Test Channel");
    expect(result.duration).toBe(120);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/info"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("should throw ApiError on non-OK response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Video not found" }),
    });

    await expect(fetchVideoInfo("https://example.com/bad")).rejects.toThrow(
      ApiError,
    );
    await expect(fetchVideoInfo("https://example.com/bad")).rejects.toThrow();
  });

  it("should include the URL in the request body", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ title: "X", uploader: null, duration: null, thumbnail: null, formats: [] }),
    });

    await fetchVideoInfo("https://example.com/video");

    const callArgs = mockFetch.mock.calls[0];
    const body = JSON.parse(callArgs[1].body);
    expect(body.url).toBe("https://example.com/video");
  });
});

describe("startDownload", () => {
  it("should return DownloadResponse on 200", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        job_id: "abc123",
        status: "queued",
        message: "Download job enqueued.",
      }),
    });

    const result = await startDownload({
      url: "https://example.com/video",
      quality: "1080p",
      audio_only: false,
    });

    expect(result.job_id).toBe("abc123");
    expect(result.status).toBe("queued");
  });

  it("should throw ApiError on 500", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal error" }),
    });

    try {
      await startDownload({ url: "https://example.com/video" });
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(500);
      expect((err as ApiError).message).toBe("Internal error");
    }
  });

  it("should send audio_only and quality in the body", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ job_id: "x", status: "queued", message: "" }),
    });

    await startDownload({
      url: "https://example.com/video",
      quality: "audio",
      audio_only: true,
    });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.audio_only).toBe(true);
    expect(body.quality).toBe("audio");
  });
});

describe("getJobStatus", () => {
  it("should return JobInfo on 200", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        job_id: "abc123",
        status: "finished",
        result: { status: "completed", url: "https://example.com", format: "best" },
        error: null,
        enqueued_at: "2025-01-01T12:00:00",
        started_at: "2025-01-01T12:00:05",
        ended_at: "2025-01-01T12:01:00",
      }),
    });

    const result = await getJobStatus("abc123");

    expect(result.job_id).toBe("abc123");
    expect(result.status).toBe("finished");
    expect(result.result?.status).toBe("completed");
  });

  it("should throw ApiError on 404", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Job not found" }),
    });

    await expect(getJobStatus("nonexistent")).rejects.toThrow("Job not found");
  });

  it("should include job_id in the URL path", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        job_id: "xyz",
        status: "queued",
        result: null,
        error: null,
        enqueued_at: null,
        started_at: null,
        ended_at: null,
      }),
    });

    await getJobStatus("xyz789");

    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("/api/download/xyz789");
  });
});

describe("extractError fallback", () => {
  it("should fall back to HTTP status text when body is not JSON", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => {
        throw new Error("Not JSON");
      },
    });

    await expect(fetchVideoInfo("https://example.com")).rejects.toThrow(
      "HTTP 503",
    );
  });
});

describe("getOrCreateSessionId", () => {
  it("should generate a UUID on first call", () => {
    const id = getOrCreateSessionId();
    expect(id).toBe("test-uuid-1234-5678");
    expect(localStorageMock.setItem).toHaveBeenCalledWith("ytdlp-session-id", "test-uuid-1234-5678");
  });

  it("should reuse existing session ID from localStorage", () => {
    localStorageMock.getItem.mockReturnValueOnce("existing-session-id");
    const id = getOrCreateSessionId();
    expect(id).toBe("existing-session-id");
    expect(crypto.randomUUID).not.toHaveBeenCalled();
  });

  it("should reuse same session ID across multiple calls", () => {
    const id1 = getOrCreateSessionId();
    localStorageMock.getItem.mockReturnValueOnce(id1);
    const id2 = getOrCreateSessionId();
    expect(id1).toBe(id2);
  });
});

describe("X-Session-ID header", () => {
  it("fetchVideoInfo should include X-Session-ID header", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ title: "X", uploader: null, duration: null, thumbnail: null, formats: [] }),
    });

    await fetchVideoInfo("https://example.com/video");

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["X-Session-ID"]).toBeDefined();
  });

  it("startDownload should include X-Session-ID header", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ job_id: "x", status: "queued", message: "" }),
    });

    await startDownload({ url: "https://example.com/video" });

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["X-Session-ID"]).toBeDefined();
  });

  it("getJobStatus should include X-Session-ID header", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        job_id: "x",
        status: "queued",
        result: null,
        error: null,
        enqueued_at: null,
        started_at: null,
        ended_at: null,
      }),
    });

    await getJobStatus("abc123");

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["X-Session-ID"]).toBeDefined();
  });
});

describe("listFiles", () => {
  it("should return list of files on 200", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        files: [
          { filename: "video.mp4", size_bytes: 1048576, size_mb: 1.0 },
          { filename: "audio.webm", size_bytes: 524288, size_mb: 0.5 },
        ],
      }),
    });

    const result = await listFiles();

    expect(result).toHaveLength(2);
    expect(result[0].filename).toBe("video.mp4");
    expect(result[1].filename).toBe("audio.webm");
  });

  it("should call GET /api/files", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ files: [] }),
    });

    await listFiles();

    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("/api/files");
  });

  it("should include X-Session-ID header", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ files: [] }),
    });

    await listFiles();

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["X-Session-ID"]).toBeDefined();
  });

  it("should throw ApiError on non-OK response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "X-Session-ID header required" }),
    });

    await expect(listFiles()).rejects.toThrow(ApiError);
  });
});