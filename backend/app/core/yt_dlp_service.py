"""
yt-dlp service wrapper.

Provides reusable functions to extract video info, trigger downloads,
and self-update yt-dlp to the latest version.

Uses yt-dlp's Python embedding API (no subprocess needed for extract/download).
The self-update uses pip internally to upgrade the yt-dlp package in-place.

These functions are called both:
  - Directly by the API (extract_info, update_yt_dlp)
  - By the RQ worker (download_video)
"""

import os
import subprocess
import sys
import importlib
from urllib.parse import urlparse, parse_qs, urlencode

import yt_dlp

from app.core.config import (
    SESSION_DIR,
    DEFAULT_OUTPUT_TEMPLATE,
    QUALITY_MAP,
    AUDIO_FORMAT,
)

# Shared yt-dlp options that help with YouTube's anti-bot measures.
# These are applied to both extract_info and download_video.
_BASE_YDL_OPTS: dict = {
    # Use the android player client which is less aggressive with 403 blocks
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        },
    },
    # Realistic User-Agent to avoid being flagged as a bot
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    },
}


def _sanitize_url(url: str) -> str:
    """
    Strip playlist/radio parameters from a YouTube URL so yt-dlp only
    processes the single video, not the entire playlist.

    Removes: list, start_radio, index, t parameters.
    Keeps: v (video ID), and the base URL.

    Examples:
      https://www.youtube.com/watch?v=X&list=RD...&start_radio=1
        -> https://www.youtube.com/watch?v=X
      https://youtu.be/X?list=...
        -> https://youtu.be/X
    """
    parsed = urlparse(url)

    # For youtu.be short URLs, just strip the query string entirely
    if parsed.hostname == "youtu.be":
        return f"https://youtu.be{parsed.path}"

    # For watch URLs, keep only the v parameter
    if parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        video_id = qs.get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    return url


def get_version() -> str:
    """Return the currently installed yt-dlp version string."""
    return yt_dlp.version.__version__


def extract_info(url: str) -> dict:
    """Fetch metadata for a URL without downloading."""
    url = _sanitize_url(url)
    ydl_opts = {
        **_BASE_YDL_OPTS,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "formats": info.get("formats", []),
        }


def download_video(
    url: str,
    quality: str = "1080p",
    audio_only: bool = False,
    session_id: str | None = None,
) -> dict:
    """
    Download a video. Called by the RQ worker.

    Downloads directly into the session's directory:
      {SESSION_DIR}/{session_id}/%(title)s [%(id)s]_{quality}.%(ext)s

    For audio_only, an FFmpeg MP3 postprocessor converts the audio stream
    to MP3 (192 kbps). The final file will have a .mp3 extension.

    Returns a dict with status info including the downloaded filename(s).
    RQ stores this as the job result, retrievable via job.result once the
    job is finished.
    """
    url = _sanitize_url(url)
    fmt = AUDIO_FORMAT if audio_only else QUALITY_MAP.get(quality, QUALITY_MAP["1080p"])
    suffix = "audio" if audio_only else quality

    # Build output template with quality suffix to prevent filename collisions
    # when the same video is downloaded at different qualities.
    # yt-dlp's %()s syntax doesn't support custom keys, so we replace manually.
    outtmpl_template = DEFAULT_OUTPUT_TEMPLATE.replace("%(quality)s", suffix)

    if session_id:
        outtmpl = f"{SESSION_DIR}/{session_id}/{outtmpl_template}"
    else:
        outtmpl = f"{SESSION_DIR}/{outtmpl_template}"

    ydl_opts = {
        **_BASE_YDL_OPTS,
        "format": fmt,
        "outtmpl": outtmpl,
        "quiet": False,
    }

    # Add MP3 postprocessor for audio-only downloads
    if audio_only:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    # Capture the actual filename(s).
    #
    # progress_hooks fire when each stream download finishes (video, audio).
    # For audio-only with MP3 postprocessing, the progress hook captures the
    # raw .mp4/.webm file which gets deleted after conversion — so we can't
    # rely on it alone.
    #
    # post_hooks fire AFTER all postprocessing is complete, receiving the
    # final filepath as a string (not a dict). This is where the .mp3 path
    # is available after FFmpegExtractAudio conversion.
    #
    # Strategy:
    # - Always use post_hooks to capture the final filename(s)
    # - Also use progress_hooks to capture files when no postprocessing happens
    #   (video downloads where yt-dlp merges video+audio without separate PPs)
    # - Deduplicate via seen_files set
    downloaded_files: list[str] = []
    seen_files: set[str] = set()

    def _capture_file(filepath: str | None) -> None:
        if filepath and filepath not in seen_files:
            basename = os.path.basename(filepath)
            seen_files.add(filepath)
            downloaded_files.append(basename)

    def _progress_hook(d: dict) -> None:
        if d.get("status") == "finished":
            _capture_file(d.get("filepath") or d.get("filename"))

    def _post_hook(filepath: str) -> None:
        _capture_file(filepath)

    ydl_opts["progress_hooks"] = [_progress_hook]
    ydl_opts["post_hooks"] = [_post_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Filter out files that were deleted during postprocessing
    # (e.g. the raw .mp4 audio file deleted after MP3 conversion)
    downloaded_files = [
        f for f in downloaded_files
        if os.path.isfile(
            os.path.join(
                SESSION_DIR, session_id, f
            ) if session_id else os.path.join(SESSION_DIR, f)
        )
    ]

    # Register files to session
    if session_id and downloaded_files:
        from app.core.queue import register_file_for_session

        for filename in downloaded_files:
            register_file_for_session(session_id, filename)

    return {
        "status": "completed",
        "url": url,
        "quality": quality,
        "format": fmt,
        "files": downloaded_files,
        "session_id": session_id,
    }


def update_yt_dlp() -> dict:
    """
    Upgrade yt-dlp to the latest version on PyPI using pip.

    This runs `pip install --upgrade yt-dlp[default,curl-cffi]` in the
    current Python environment. After upgrading, the new version takes
    effect immediately for new extract_info/download_video calls —
    no container restart needed.

    Returns a dict with the old version, new version, and pip stdout/stderr.
    """
    old_version = get_version()

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default,curl-cffi]"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        return {
            "status": "failed",
            "old_version": old_version,
            "error": result.stderr.strip() or result.stdout.strip(),
            "returncode": result.returncode,
        }

    # Reload the module so get_version() reflects the new version
    importlib.reload(yt_dlp)

    new_version = get_version()
    return {
        "status": "success",
        "old_version": old_version,
        "new_version": new_version,
        "stdout": result.stdout.strip(),
    }