/**
 * App — main application component.
 *
 * Flow:
 *   1. User enters a URL -> fetchVideoInfo -> show VideoInfoCard
 *   2. User clicks Download -> startDownload -> add JobStatusCard
 *   3. JobStatusCard polls until finished/failed
 *   4. User can dismiss jobs and start over
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { UrlInput } from "./components/UrlInput";
import { VideoInfoCard, type DownloadOptions } from "./components/VideoInfoCard";
import { JobStatusCard } from "./components/JobStatusCard";
import { ErrorMessage } from "./components/ErrorMessage";
import { fetchVideoInfo, startDownload, getJobStatus, ApiError } from "./lib/api";
import type { VideoInfo } from "./types";

const POLL_INTERVAL_MS = 2000;

interface ActiveJob {
  jobId: string;
  url: string;
}

export function App() {
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [videoInfo, setVideoInfo] = useState<VideoInfo | null>(null);
  const [currentUrl, setCurrentUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<ActiveJob[]>([]);

  // Ref to track if the component is still mounted — allows the polling
  // loop in handleDownload to exit early if the user navigates away.
  const downloadActiveRef = useRef(true);
  useEffect(() => {
    downloadActiveRef.current = true;
    return () => { downloadActiveRef.current = false; };
  }, []);

  const handleFetchInfo = useCallback(async (url: string) => {
    setLoading(true);
    setError(null);
    setVideoInfo(null);
    setCurrentUrl(url);
    try {
      const info = await fetchVideoInfo(url);
      setVideoInfo(info);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to fetch video info",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const handleDownload = useCallback(
    async (opts: DownloadOptions) => {
      if (!videoInfo) return;
      setDownloading(true);
      setError(null);
      try {
        // Remove any existing job cards for the same URL so we don't
        // accumulate duplicate entries when re-downloading the same video.
        setJobs((prev) => prev.filter((j) => j.url !== currentUrl));

        const res = await startDownload({
          url: currentUrl,
          format: opts.format,
          audio_only: opts.audio_only,
        });
        // Avoid duplicate job cards when backend returns an already-queued job
        setJobs((prev) => {
          if (prev.some((j) => j.jobId === res.job_id)) {
            return prev;
          }
          return [...prev, { jobId: res.job_id, url: currentUrl }];
        });

        // Poll until the job reaches a terminal state.
        // This keeps the download button disabled for the entire duration
        // of the actual yt-dlp download, preventing double-clicks from
        // enqueuing redundant jobs.
        const jobId = res.job_id;
        while (downloadActiveRef.current) {
          try {
            const info = await getJobStatus(jobId);
            if (info.status === "finished" || info.status === "failed") {
              break;
            }
          } catch {
            // Polling error — keep waiting, JobStatusCard shows its own errors
          }
          if (!downloadActiveRef.current) break; // unmounted or cancelled
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        }
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Failed to start download",
        );
      } finally {
        setDownloading(false);
      }
    },
    [videoInfo, currentUrl],
  );

  const handleDismissJob = useCallback((jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.jobId !== jobId));
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-8">
      <div className="w-full max-w-2xl space-y-6">
        <h1 className="text-2xl font-bold text-slate-100 text-center">
          yt-dlp Web
        </h1>

        {/* URL Input */}
        <UrlInput onSubmit={handleFetchInfo} loading={loading} />

        {/* Error */}
        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        {/* Video Info + Download Form */}
        {videoInfo && (
          <VideoInfoCard
            info={videoInfo}
            onDownload={handleDownload}
            downloading={downloading}
          />
        )}

        {/* Job Status Cards */}
        {jobs.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide">
              Downloads
            </h2>
            {jobs.map((job) => (
              <JobStatusCard
                key={job.jobId}
                jobId={job.jobId}
                url={job.url}
                onDismiss={handleDismissJob}
              />
            ))}
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-slate-600 pt-4">
          Powered by{" "}
          <a
            href="https://github.com/yt-dlp/yt-dlp"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-500 hover:text-slate-400"
          >
            yt-dlp
          </a>
        </p>
      </div>
    </div>
  );
}