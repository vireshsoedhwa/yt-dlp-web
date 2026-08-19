"""Configuration and settings."""

import os

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/app/downloads")
DEFAULT_OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
DEFAULT_FORMAT = "bestvideo+bestaudio/best"
AUDIO_FORMAT = "bestaudio/best"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "downloads"

# Download archive -- yt-dlp records video IDs to skip re-downloads
ARCHIVE_FILE = os.environ.get("ARCHIVE_FILE", f"{DOWNLOAD_DIR}/.ytdlp-archive.txt")

# Dedup -- TTL for URL-to-job mapping in Redis (seconds)
DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "3600"))

# Purge -- max age in hours before unclaimed files are deleted
PURGE_MAX_AGE_HOURS = int(os.environ.get("PURGE_MAX_AGE_HOURS", "3"))

# Session isolation -- directory for per-session hard links
SESSION_DIR = os.environ.get("SESSION_DIR", f"{DOWNLOAD_DIR}/.session")