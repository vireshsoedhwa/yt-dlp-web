/**
 * JobStatusCard — displays the status of a download job and polls for updates.
 *
 * Receives a jobId and the URL being downloaded.
 * Polls GET /api/download/{job_id} every 2 seconds while the job is active.
 * Shows status badge, timestamps, error info if failed, and download buttons
 * when the job is finished.
 *
 * Download buttons use fetch() with the X-Session-ID header (not <a> tags)
 * because browser <a> clicks don't support custom headers.
 *
 * Implementation note: uses a ref to track the latest job status so the
 * interval persists for the component's lifetime. The interval checks
 * the ref and clears itself when the job reaches a terminal state
 * (finished/failed). This avoids the tight-loop bug caused by putting
 * `job` in the useEffect dependency array.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { getJobStatus, downloadFile, ApiError } from "../lib/api";
import type { JobInfo, JobStatus as StatusType } from "../types";

interface JobStatusCardProps {
  jobId: string;
  url: string;
  onDismiss: (jobId: string) => void;
}

const POLL_INTERVAL_MS = 2000;

const STATUS_STYLES: Record<StatusType, string> = {
  queued: "bg-yellow-900 text-yellow-200 border-yellow-700",
  started: "bg-blue-900 text-blue-200 border-blue-700",
  finished: "bg-green-900 text-green-200 border-green-700",
  failed: "bg-red-900 text-red-200 border-red-700",
};

export function JobStatusCard({ jobId, url, onDismiss }: JobStatusCardProps) {
  const [job, setJob] = useState<JobInfo | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<string | null>(null);

  // Ref to track the latest job status so the interval can check it
  // without re-triggering the useEffect.
  const jobRef = useRef<JobInfo | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const info = await getJobStatus(jobId);
      jobRef.current = info;
      setJob(info);
      setPollError(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setPollError(err.message);
      } else {
        setPollError("Failed to fetch job status");
      }
    }
  }, [jobId]);

  useEffect(() => {
    // Fetch immediately on mount
    fetchStatus();

    // Set up a single interval that persists for the component's lifetime.
    // The interval checks jobRef.current to know when to stop.
    const interval = setInterval(() => {
      const current = jobRef.current;
      if (current && (current.status === "finished" || current.status === "failed")) {
        clearInterval(interval);
        return;
      }
      fetchStatus();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleDownload = useCallback(async (filename: string) => {
    setDownloading(filename);
    try {
      const blob = await downloadFile(filename);
      // Create a temporary object URL and trigger download
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objUrl);

      // Show success state, then auto-dismiss the card after 3 seconds
      setDownloaded(filename);
      setTimeout(() => {
        onDismiss(jobId);
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        setPollError(`Download failed: ${err.message}`);
      } else {
        setPollError("Download failed");
      }
    } finally {
      setDownloading(null);
    }
  }, [onDismiss, jobId]);

  const status = job?.status ?? "queued";
  const isDone = status === "finished" || status === "failed";
  const files = job?.result?.files ?? [];

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium border ${STATUS_STYLES[status]}`}
            >
              {status}
            </span>
            {!isDone && (
              <span className="text-xs text-slate-500">polling...</span>
            )}
          </div>
          <p className="text-sm text-slate-300 truncate" title={url}>
            {url}
          </p>
          {job?.result?.format && (
            <p className="text-xs text-slate-500 mt-1">
              Format: {job.result.format}
            </p>
          )}
          {job?.error && (
            <p className="text-xs text-red-400 mt-1">{job.error}</p>
          )}
          {pollError && (
            <p className="text-xs text-red-400 mt-1">{pollError}</p>
          )}
          {isDone && files.length > 0 && (
            <div className="mt-2 space-y-1">
              {files.map((filename, i) => (
                <button
                  key={filename + i}
                  onClick={() => handleDownload(filename)}
                  disabled={downloading !== null || downloaded !== null}
                  className="inline-flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {downloading === filename ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 12a8 8 0 018-8" />
                      </svg>
                      downloading...
                    </>
                  ) : downloaded === filename ? (
                    <>
                      <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      <span className="text-green-400">downloaded</span>
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      {filename}
                    </>
                  )}
                </button>
              ))}
            </div>
          )}
          {isDone && files.length === 0 && status === "finished" && (
            <p className="text-xs text-slate-500 mt-1">
              Download complete (filename unavailable)
            </p>
          )}
        </div>
        <button
          onClick={() => onDismiss(jobId)}
          className="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Dismiss job"
        >
          ✕
        </button>
      </div>
    </div>
  );
}