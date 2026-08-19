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
import re
import glob
import subprocess
import sys
import importlib

import yt_dlp

from app.core.config import (
    DOWNLOAD_DIR,
    DEFAULT_OUTPUT_TEMPLATE,
    DEFAULT_FORMAT,
    AUDIO_FORMAT,
    ARCHIVE_FILE,
)

# Regex to extract video ID from filenames matching the output template
# %(title)s [%(id)s].%(ext)s -> captures content inside the last [...]
_VIDEO_ID_RE = re.compile(r"\[([^\]]+)\]")


# Shared yt-dlp options that help with YouTube's anti-bot measures.
# These are applied to both extract_info and download_video.
# NOTE: download_archive is NOT here -- it's only in download_video,
# because extract_info should always fetch metadata regardless of archive.
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


def get_version() -> str:
    """Return the currently installed yt-dlp version string."""
    return yt_dlp.version.__version__


def extract_info(url: str) -> dict:
    """Fetch metadata for a URL without downloading."""
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


def _recover_files_from_disk(url: str) -> list[str]:
    """
    Recover downloaded filenames when yt-dlp skips a download (archive hit).

    When a video is already in the archive, yt-dlp doesn't fire any progress
    or postprocessor hooks, so the normal capture mechanism produces an empty
    list. This function extracts the video ID from the URL (using a lightweight
    yt-dlp extract_info call with skip_download), then globs DOWNLOAD_DIR for
    a file matching the pattern "* [video_id].*".

    Returns a list of basenames of files found on disk, or an empty list if
    the file couldn't be found.
    """
    info_opts = {
        **_BASE_YDL_OPTS,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return []

    video_id = info.get("id")
    if not video_id:
        return []

    files: list[str] = []

    # Glob DOWNLOAD_DIR for any file matching * [video_id].*
    # This is more robust than rendering the template ourselves because
    # yt-dlp sanitizes titles (removes /, :, etc.) and may pick a different
    # extension than extract_info reports.
    # NOTE: glob treats [ ] as character classes, so we escape them.
    safe_id = glob.escape(f"[{video_id}]")
    pattern = os.path.join(DOWNLOAD_DIR, f"* {safe_id}.*")
    for filepath in sorted(glob.glob(pattern)):
        basename = os.path.basename(filepath)
        # Skip hidden files and the archive file
        if basename.startswith("."):
            continue
        files.append(basename)

    return files


def download_video(
    url: str,
    format_str: str | None = None,
    audio_only: bool = False,
    output_template: str | None = None,
    session_id: str | None = None,
) -> dict:
    """
    Download a video. Called by the RQ worker.

    Returns a dict with status info including the downloaded filename(s).
    If session_id is provided, files are registered to that session via
    register_file_for_session() and hard links are created.

    RQ stores this as the job result, retrievable via job.result once the
    job is finished.
    """
    fmt = AUDIO_FORMAT if audio_only else (format_str or DEFAULT_FORMAT)
    outtmpl = output_template or DEFAULT_OUTPUT_TEMPLATE

    ydl_opts = {
        **_BASE_YDL_OPTS,
        "format": fmt,
        "outtmpl": f"{DOWNLOAD_DIR}/{outtmpl}",
        "quiet": False,
        # Download archive -- skip videos already downloaded (by video ID)
        "download_archive": ARCHIVE_FILE,
    }

    # Capture the actual filename(s) via both progress_hooks and postprocessor_hooks.
    # progress_hooks fire when each stream download finishes (video, audio separately).
    # postprocessor_hooks fire when FFmpeg finishes merging/converting -- this is
    # where the FINAL filename is available (the merged output).
    # We use a set to deduplicate, since progress_hooks may fire for intermediate
    # files that get deleted during the merge.
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

    def _postprocessor_hook(d: dict) -> None:
        # postprocessor_hooks fire with status "finished" and the final filepath
        # after FFmpeg merging/conversion is complete.
        if d.get("status") == "finished":
            _capture_file(d.get("filepath") or d.get("filename"))

    ydl_opts["progress_hooks"] = [_progress_hook]
    ydl_opts["postprocessor_hooks"] = [_postprocessor_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Fallback: if no files were captured (hooks didn't fire), the video was
    # likely already in the archive and yt-dlp skipped the download. The file
    # is on disk but we never got a progress/postprocessor callback. Recover
    # by extracting the video ID and globbing DOWNLOAD_DIR for a matching file.
    if not downloaded_files:
        downloaded_files = _recover_files_from_disk(url)

    # Register files to session and create hard links
    if session_id and downloaded_files:
        from app.core.queue import register_file_for_session
        from app.core.files_service import create_session_link

        for filename in downloaded_files:
            register_file_for_session(session_id, filename)
            create_session_link(session_id, filename)

    return {
        "status": "completed",
        "url": url,
        "format": fmt,
        "files": downloaded_files,
        "session_id": session_id,
    }


def parse_video_id(filename: str) -> str | None:
    """
    Extract the video ID from a filename matching the pattern
    'Title [video_id].ext' (from the DEFAULT_OUTPUT_TEMPLATE).

    Returns None if no bracket-enclosed ID is found.
    """
    if not filename:
        return None
    matches = _VIDEO_ID_RE.findall(filename)
    return matches[-1] if matches else None


def remove_from_archive(video_id: str) -> None:
    """
    Remove a video ID from the yt-dlp download archive file.

    Reads the archive line by line, filters out lines containing the
    video_id, and writes the remaining lines back.
    Handles missing file gracefully (no-op).
    """
    if not os.path.isfile(ARCHIVE_FILE):
        return

    with open(ARCHIVE_FILE, "r") as f:
        lines = f.readlines()

    remaining = [line for line in lines if video_id not in line]

    # Only write if something was removed (avoid unnecessary I/O)
    if len(remaining) != len(lines):
        with open(ARCHIVE_FILE, "w") as f:
            f.writelines(remaining)


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