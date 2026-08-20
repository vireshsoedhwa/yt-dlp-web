/**
 * UrlInput — text field + submit button for entering a video URL.
 *
 * Controlled component: parent owns the value state.
 * Calls onSubmit(url) when the form is submitted (Enter or button click).
 */

import { useState, type FormEvent } from "react";

interface UrlInputProps {
  onSubmit: (url: string) => void;
  loading?: boolean;
  placeholder?: string;
}

export function UrlInput({
  onSubmit,
  loading = false,
  placeholder = "Paste a video URL...",
}: UrlInputProps) {
  const [url, setUrl] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (trimmed) {
      onSubmit(trimmed);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-2 w-full">
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onFocus={(e) => e.target.select()}
        placeholder={placeholder}
        disabled={loading}
        className="flex-1 px-4 py-3 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 disabled:opacity-50 min-w-0"
        aria-label="Video URL"
      />
      <button
        type="submit"
        disabled={loading || !url.trim()}
        className="px-6 py-3 rounded-lg bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors sm:whitespace-nowrap"
      >
        {loading ? "Loading..." : "Fetch Info"}
      </button>
    </form>
  );
}