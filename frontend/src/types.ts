/** Shared TypeScript types matching the FastAPI backend schemas. */

export interface VideoFormat {
  format_id: string;
  ext: string;
  resolution: string;
  [key: string]: unknown;
}

export interface VideoInfo {
  title: string;
  uploader: string | null;
  duration: number | null;
  thumbnail: string | null;
  formats: VideoFormat[];
}

export interface DownloadRequest {
  url: string;
  quality?: string;
  audio_only?: boolean;
}

export interface DownloadResponse {
  job_id: string;
  status: string;
  message: string;
}

export type JobStatus = "queued" | "started" | "finished" | "failed";

export interface JobProgress {
  percentage: string;
  speed: string;
  eta: string;
  downloaded_bytes: number;
  total_bytes: number;
}

export interface JobResult {
  status: string;
  url: string;
  format: string;
  files: string[];
  quality?: string;
  title?: string;
  thumbnail?: string | null;
  uploader?: string | null;
}

export interface JobInfo {
  job_id: string;
  status: JobStatus;
  result: JobResult | null;
  error: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  progress: JobProgress | null;
}

export interface FileInfo {
  filename: string;
  size_bytes: number;
  size_mb: number;
}

export interface SessionJob {
  job_id: string;
  url: string;
  status: JobStatus;
  result: JobResult | null;
  error: string | null;
  ended_at: string | null; // ISO timestamp when job finished, null if still running
}