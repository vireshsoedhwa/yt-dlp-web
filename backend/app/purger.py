"""
Background purge scheduler — runs in a thread on the worker container.

Scans ALL session directories every PURGE_INTERVAL_SECONDS for files
older than PURGE_MAX_AGE_HOURS. Deletes old files, cleans up empty
session directories, and clears stale Redis mappings.

This runs in a background thread alongside the RQ worker — it does not
interfere with job processing.
"""

import os
import time
import threading
import logging

from app.core.config import SESSION_DIR, PURGE_MAX_AGE_HOURS, PURGE_INTERVAL_SECONDS
from app.core.queue import (
    get_files_for_session,
    clear_file_for_session,
    clear_all_files_for_session,
    clear_all_jobs_for_session,
)

logger = logging.getLogger("purger")


def _purge_all_sessions(max_age_hours: int) -> dict:
    """
    Scan ALL session directories under SESSION_DIR and purge old files.

    Unlike the per-session purge endpoint, this scans every session
    directory on disk — not just sessions with active Redis mappings.
    This catches abandoned sessions whose Redis mappings may have expired.

    Returns: {"sessions_scanned": N, "files_purged": N, "freed_bytes": N}
    """
    max_age_seconds = max_age_hours * 3600
    now = time.time()

    sessions_scanned = 0
    files_purged = 0
    freed_bytes = 0

    if not os.path.isdir(SESSION_DIR):
        return {"sessions_scanned": 0, "files_purged": 0, "freed_bytes": 0}

    # List all session directories under .session/
    for entry in os.listdir(SESSION_DIR):
        session_path = os.path.join(SESSION_DIR, entry)
        if not os.path.isdir(session_path):
            continue

        session_id = entry
        sessions_scanned += 1

        # Get files for this session from Redis (if mappings exist)
        filenames = get_files_for_session(session_id)

        # Also scan the directory for files not in Redis (orphaned)
        dir_files = set()
        for f in os.listdir(session_path):
            if not f.startswith("."):
                dir_files.add(f)

        # Combine: files from Redis + files on disk
        all_files = set(filenames) | dir_files

        for filename in all_files:
            filepath = os.path.join(session_path, filename)
            if not os.path.isfile(filepath):
                # File gone but Redis mapping exists — clean up
                clear_file_for_session(session_id, filename)
                continue

            file_mtime = os.path.getmtime(filepath)
            age_seconds = now - file_mtime

            if age_seconds < max_age_seconds:
                continue

            # File is old — delete it
            size = os.path.getsize(filepath)
            os.remove(filepath)
            clear_file_for_session(session_id, filename)
            files_purged += 1
            freed_bytes += size
            logger.info(
                f"Purged {filename} from session {session_id} "
                f"({size} bytes, {age_seconds/3600:.1f}h old)"
            )

        # Check remaining files on disk (not just Redis)
        remaining = [f for f in os.listdir(session_path) if not f.startswith(".")]
        if not remaining:
            # Session directory is empty — remove it and clear Redis
            try:
                os.rmdir(session_path)
            except OSError:
                pass
            clear_all_files_for_session(session_id)
            clear_all_jobs_for_session(session_id)

    return {
        "sessions_scanned": sessions_scanned,
        "files_purged": files_purged,
        "freed_bytes": freed_bytes,
    }


def _purge_loop():
    """Background loop that runs the purge on a fixed interval."""
    logger.info(
        f"Purger started: interval={PURGE_INTERVAL_SECONDS}s, "
        f"max_age={PURGE_MAX_AGE_HOURS}h"
    )

    while True:
        try:
            result = _purge_all_sessions(PURGE_MAX_AGE_HOURS)
            if result["files_purged"] > 0:
                logger.info(f"Purge complete: {result}")
        except Exception as e:
            logger.error(f"Purge error: {e}")

        time.sleep(PURGE_INTERVAL_SECONDS)


def start_purge_thread():
    """Start the background purge thread. Call once at worker startup."""
    thread = threading.Thread(target=_purge_loop, daemon=True, name="purger")
    thread.start()
    return thread