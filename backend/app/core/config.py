"""Configuration and settings."""

import os

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/app/downloads")
DEFAULT_OUTPUT_TEMPLATE = "%(title)s [%(id)s]_%(quality)s.%(ext)s"
DEFAULT_FORMAT = "bestvideo+bestaudio/best"
AUDIO_FORMAT = "bestaudio/best"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "downloads"

# Purge -- max age in hours before unclaimed files are deleted
PURGE_MAX_AGE_HOURS = int(os.environ.get("PURGE_MAX_AGE_HOURS", "3"))

# Purge -- how often the background purger runs (in seconds)
PURGE_INTERVAL_SECONDS = int(os.environ.get("PURGE_INTERVAL_SECONDS", "3600"))  # 1 hour

# Job card -- how long the download card stays visible after job finishes (hours)
JOB_CARD_TTL_HOURS = int(os.environ.get("JOB_CARD_TTL_HOURS", "2"))

# Serving flag -- TTL for the "file is being downloaded" Redis flag (seconds)
# Protects files from being purged while actively being downloaded.
SERVING_FLAG_TTL_SECONDS = int(os.environ.get("SERVING_FLAG_TTL_SECONDS", "3600"))

# Session isolation -- directory for per-session downloads
SESSION_DIR = os.environ.get("SESSION_DIR", f"{DOWNLOAD_DIR}/.session")

# Quality -> yt-dlp format string mapping
QUALITY_MAP = {
    "1080p": "bestvideo[height<=1080]+bestaudio/best",
    "720p": "bestvideo[height<=720]+bestaudio/best",
    "480p": "bestvideo[height<=480]+bestaudio/best",
    "360p": "bestvideo[height<=360]+bestaudio/best",
    "audio": "bestaudio/best",
}