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