/**
 * VideoInfoCard — displays metadata returned by POST /api/info.
 *
 * Shows thumbnail, title, uploader, duration, and format count.
 * Calls onDownload(opts) when the user clicks "Download".
 */

import { useState, useRef, useEffect } from "react";
import type { VideoInfo } from "../types";

export interface DownloadOptions {
  format: string;
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
  const [audioOnly, setAudioOnly] = useState(false);
  const [formatStr, setFormatStr] = useState("bestvideo+bestaudio/best");

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
      format: audioOnly ? "bestaudio/best" : formatStr,
      audio_only: audioOnly,
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
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={audioOnly}
              onChange={(e) => setAudioOnly(e.target.checked)}
              className="accent-blue-500"
            />
            Audio only
          </label>

          {!audioOnly && (
            <input
              type="text"
              value={formatStr}
              onChange={(e) => setFormatStr(e.target.value)}
              placeholder="Format (e.g. bestvideo+bestaudio/best)"
              className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm focus:outline-none focus:border-blue-500"
            />
          )}

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
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}