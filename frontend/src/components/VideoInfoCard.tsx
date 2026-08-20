/**
 * VideoInfoCard — displays metadata returned by POST /api/info.
 *
 * Shows thumbnail, title, uploader, duration, and format count.
 * Calls onDownload(opts) when the user clicks "Download".
 */

import { useState, useRef, useEffect } from "react";
import type { VideoInfo } from "../types";

export interface DownloadOptions {
  quality: string;
  audio_only: boolean;
}

interface VideoInfoCardProps {
  info: VideoInfo;
  onDownload: (opts: DownloadOptions) => void;
  downloading?: boolean;
}

export function VideoInfoCard({
  info,
  onDownload,
  downloading = false,
}: VideoInfoCardProps) {
  const [quality, setQuality] = useState("1080p");
  const isAudio = quality === "audio";

  // Ref guard prevents double-clicks from firing onDownload twice
  // before React re-renders with the `clicked` state or `downloading` prop.
  const clickLock = useRef(false);
  // State drives the visual feedback (disabled, grey, label).
  // Ref change alone doesn't trigger a re-render, so we need both.
  const [clicked, setClicked] = useState(false);

  // Reset the lock when downloading finishes so the user can start another download
  useEffect(() => {
    if (!downloading) {
      clickLock.current = false;
      setClicked(false);
    }
  }, [downloading]);

  function handleDownload() {
    if (clickLock.current) return;
    clickLock.current = true;
    setClicked(true);
    onDownload({
      quality,
      audio_only: isAudio,
    });
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      {/* Thumbnail */}
      {info.thumbnail && (
        <img
          src={info.thumbnail}
          alt={info.title}
          className="w-full max-h-64 object-cover"
        />
      )}

      {/* Metadata */}
      <div className="p-5 space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">{info.title}</h2>
          {info.uploader && (
            <p className="text-sm text-slate-400 mt-1">{info.uploader}</p>
          )}
          {info.duration != null && (
            <p className="text-sm text-slate-400 mt-1">
              Duration: {formatDuration(info.duration)}
            </p>
          )}
          <p className="text-sm text-slate-500 mt-1">
            {info.formats.length} formats available
          </p>
        </div>

        {/* Download controls */}
        <div className="space-y-3 border-t border-slate-700 pt-4">
          {/* Quality pills — all always visible; selected one is green */}
          <div className="flex flex-wrap gap-2">
            {(["1080p", "720p", "480p", "360p"] as const).map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setQuality(q)}
                className="px-3 py-1.5 rounded-full text-sm font-medium transition-colors"
                style={
                  quality === q
                    ? { backgroundColor: "#16a34a", color: "#ffffff" }
                    : { backgroundColor: "#334155", color: "#cbd5e1" }
                }
                aria-pressed={quality === q}
              >
                {q}
              </button>
            ))}
            {/* Audio only pill — in the same row */}
            <button
              type="button"
              onClick={() => setQuality("audio")}
              className="px-3 py-1.5 rounded-full text-sm font-medium transition-colors"
              style={
                isAudio
                  ? { backgroundColor: "#16a34a", color: "#ffffff" }
                  : { backgroundColor: "#334155", color: "#cbd5e1" }
              }
              aria-pressed={isAudio}
            >
              Audio only
            </button>
          </div>

          <button
            onClick={handleDownload}
            disabled={downloading || clicked}
            className="w-full px-4 py-2.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed inline-flex items-center justify-center gap-2"
            style={
              downloading || clicked
                ? { backgroundColor: "#475569", color: "#94a3b8" }
                : { backgroundColor: "#16a34a", color: "#ffffff" }
            }
          >
            {downloading || clicked ? (
              <>
                <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 12a8 8 0 018-8" />
                </svg>
                Downloading...
              </>
            ) : (
              "Download"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}