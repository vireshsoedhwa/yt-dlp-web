/**
 * API client — thin fetch wrappers for the backend.
 *
 * Every function corresponds to one backend endpoint:
 *   fetchVideoInfo  -> POST /api/info
 *   startDownload   -> POST /api/download
 *   getJobStatus    -> GET  /api/download/{job_id}
 *   listFiles       -> GET  /api/files
 *
 * Session management: a session ID (UUID) is generated on first visit,
 * stored in localStorage, and sent as X-Session-ID header with every
 * request for file isolation.
 *
 * In dev, Vite proxies /api to the backend (see vite.config.ts proxy).
 * In production, nginx handles routing.
 */

import type {
  VideoInfo,
  DownloadRequest,
  DownloadResponse,
  JobInfo,
  FileInfo,
  SessionJob,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const SESSION_KEY = "ytdlp-session-id";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Get or create a session ID (UUID) for file isolation. */
export function getOrCreateSessionId(): string {
  let sessionId = localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

/** Build headers with session ID for all API requests. */
function _headers(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "X-Session-ID": getOrCreateSessionId(),
    ...extra,
  };
}

/** POST /api/info — extract video metadata without downloading. */
export async function fetchVideoInfo(url: string): Promise<VideoInfo> {
  const res = await fetch(`${API_BASE}/api/info`, {
    method: "POST",
    headers: _headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<VideoInfo>;
}

/** POST /api/download — enqueue a download job, returns immediately. */
export async function startDownload(
  req: DownloadRequest,
): Promise<DownloadResponse> {
  const res = await fetch(`${API_BASE}/api/download`, {
    method: "POST",
    headers: _headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<DownloadResponse>;
}

/** GET /api/download/{job_id} — poll job status. */
export async function getJobStatus(jobId: string): Promise<JobInfo> {
  const res = await fetch(`${API_BASE}/api/download/${jobId}`, {
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<JobInfo>;
}

/** GET /api/files — list files for the current session. */
export async function listFiles(): Promise<FileInfo[]> {
  const res = await fetch(`${API_BASE}/api/files`, {
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  const data = await res.json() as { files: FileInfo[] };
  return data.files;
}

/** GET /api/files/{filename} — download a file, returns blob. */
export async function downloadFile(filename: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}`, {
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

/** GET /api/jobs — list all jobs for the current session. */
export async function getJobs(): Promise<SessionJob[]> {
  const res = await fetch(`${API_BASE}/api/jobs`, {
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  const data = await res.json() as { jobs: SessionJob[] };
  return data.jobs;
}

/** DELETE /api/jobs/{job_id} — dismiss a job from the session. */
export async function dismissJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
    method: "DELETE",
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
}

/** Extract error detail from a non-OK fetch response. */
async function extractError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.detail ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}