# Scheduled Purge — Automatic Background Cleanup of Unclaimed Files

## Overview

Currently, the purge endpoint (`POST /api/purge`) only runs when manually called. If a user downloads a video but never clicks the file link to save it to their computer, the file sits on disk forever. There is no automatic cleanup.

This plan adds a background scheduler to the worker container that runs the purge logic every hour, scanning ALL session directories for files older than `PURGE_MAX_AGE_HOURS` (default: 3 hours). No user interaction required.

## Goals

1. Automatic cleanup — no user or cron needed
2. Scans ALL sessions, not just the requesting session (unlike the current purge endpoint which is per-session)
3. Runs on the worker container (already running, no new container needed)
4. Configurable interval (default: every 1 hour)
5. Configurable max age (existing: 3 hours)
6. Logs what was purged for debugging
7. Cleans up empty session directories
8. Does not interfere with the RQ worker's main job processing

## Design Decision: Threading vs Separate Process

**Option A: Background thread in the worker process (recommended)**
- The worker process (`python -m app.worker`) starts a background thread that runs the purge loop
- The RQ worker continues processing download jobs on the main thread
- No new container, no new process, no new dependency
- Simple: one function, one thread, one loop

**Option B: Separate container with its own entry point**
- New `purger` service in docker-compose that runs `python -m app.purger`
- Completely isolated from the worker
- More Docker config, another container to manage
- Overkill for a simple periodic file scan

**Option C: APScheduler or RQ Scheduler**
- Use a library for scheduling
- RQ already has a scheduler (`worker.work(with_scheduler=True)`) but it's for scheduling jobs, not for running periodic background tasks in the worker process itself
- APScheduler adds a dependency for something that can be done with `time.sleep` and a thread

**Decision: Option A** — background thread in the worker. Simplest, no new deps, no new containers.

## Backend Changes

### 1. config.py — add purge interval

```python
# Purge -- how often the background purger runs (in seconds)
PURGE_INTERVAL_SECONDS = int(os.environ.get("PURGE_INTERVAL_SECONDS", "3600"))  # 1 hour
```

### 2. New file: backend/app/purger.py

```python
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
from app.core.queue import get_redis, get_files_for_session, clear_file_for_session, clear_all_files_for_session
from app.core.files_service import get_session_dir, delete_session_file

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

        session_has_files = False

        for filename in all_files:
            filepath = os.path.join(session_path, filename)
            if not os.path.isfile(filepath):
                # File gone but Redis mapping exists — clean up
                clear_file_for_session(session_id, filename)
                continue

            file_mtime = os.path.getmtime(filepath)
            age_seconds = now - file_mtime

            if age_seconds < max_age_seconds:
                session_has_files = True
                continue

            # File is old — delete it
            size = os.path.getsize(filepath)
            os.remove(filepath)
            clear_file_for_session(session_id, filename)
            files_purged += 1
            freed_bytes += size
            logger.info(f"Purged {filename} from session {session_id} "
                       f"({size} bytes, {age_seconds/3600:.1f}h old)")

        # Check remaining files on disk (not just Redis)
        remaining = [f for f in os.listdir(session_path) if not f.startswith(".")]
        if not remaining:
            # Session directory is empty — remove it and clear Redis
            try:
                os.rmdir(session_path)
            except OSError:
                pass
            clear_all_files_for_session(session_id)

    return {
        "sessions_scanned": sessions_scanned,
        "files_purged": files_purged,
        "freed_bytes": freed_bytes,
    }


def _purge_loop():
    """Background loop that runs the purge on a fixed interval."""
    logger.info(f"Purger started: interval={PURGE_INTERVAL_SECONDS}s, "
               f"max_age={PURGE_MAX_AGE_HOURS}h")

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
```

### 3. worker.py — start purge thread on startup

```python
from app.purger import start_purge_thread

def run_worker():
    """Start the RQ worker and background purge thread."""
    conn = get_redis()
    queue = get_queue()

    # Start background purge thread
    start_purge_thread()

    worker = Worker([queue], connection=conn)
    print(f"[worker] Listening on queue '{QUEUE_NAME}'...")
    worker.work(with_scheduler=True)
```

### 4. docker-compose.yml — add PURGE_INTERVAL_SECONDS env var

```yaml
# On both backend and worker:
environment:
  - PURGE_INTERVAL_SECONDS=3600  # run purge every 1 hour
```

### 5. requirements.txt — add logging config (optional)

No new dependencies needed. Python's built-in `logging` and `threading` modules are sufficient.

## How It Works

### Startup
```
Worker container starts
  -> run_worker() called
  -> start_purge_thread() spawns a daemon thread
  -> Main thread: RQ worker listens for download jobs (unchanged)
  -> Purger thread: sleeps for PURGE_INTERVAL_SECONDS, then runs _purge_all_sessions()
```

### Purge cycle
```
Every PURGE_INTERVAL_SECONDS (default: 3600s = 1 hour):
  -> List all directories under .session/
  -> For each session directory:
     -> List files on disk + files in Redis (union)
     -> For each file:
        -> If file mtime > PURGE_MAX_AGE_HOURS: delete file, clear Redis mapping
        -> If file is gone but Redis mapping exists: clear Redis mapping
     -> If session directory is empty: remove directory, clear all Redis mappings
  -> Log summary: sessions scanned, files purged, bytes freed
  -> Sleep for PURGE_INTERVAL_SECONDS
```

### Daemon thread
- The purge thread is a `daemon=True` thread — it dies when the main process exits
- No graceful shutdown needed — if the worker restarts, the thread restarts with it
- If the purge is running when the worker shuts down, it just stops mid-scan; the next cycle picks up where it left off (files are checked by mtime, not by "last scanned")

## Key Differences from the Per-Session Purge Endpoint

| Aspect | POST /api/purge (existing) | Background Purger (new) |
|--------|---------------------------|------------------------|
| Scope | Single session (X-Session-ID) | ALL sessions on disk |
| Trigger | User calls endpoint | Automatic, every hour |
| Redis scan | Files for one session | Files for all sessions + orphaned files on disk |
| Empty dir cleanup | Yes (per session) | Yes (all sessions) |
| Logging | Returns JSON to caller | Logs to stdout (visible in docker logs) |

The background purger also catches **orphaned files** — files that exist on disk but have no Redis mapping (e.g., Redis was restarted and lost data, or a file was created outside the normal flow). The per-session endpoint only checks Redis mappings, so it would miss these.

## Edge Cases

1. **Redis is down when purge runs:** `_purge_all_sessions` catches exceptions and logs them. Files on disk are still scanned and deleted by mtime. Redis cleanup (clear_file_for_session) will fail silently — the stale mappings will be cleaned on the next successful run.

2. **Worker restarts mid-purge:** No problem. The daemon thread dies, the new worker starts a new thread, and the next cycle starts fresh. Files are checked by mtime, not by scan history.

3. **Large number of sessions:** The purge scans all directories under `.session/`. If there are thousands of sessions, this could take a few seconds. It runs in a background thread so it doesn't block job processing. The `os.listdir` + `os.path.getmtime` calls are fast (filesystem metadata, no file reading).

4. **File is being downloaded when purge runs:** The file's mtime was set when yt-dlp created it. If the user is currently downloading it via the API, the `FileResponse` is already streaming — `os.remove` would fail or the OS would handle it (on Linux, the file is unlinked but the file descriptor stays open until the response finishes). In practice, a 3-hour-old file being actively downloaded is extremely unlikely.

5. **Clock skew:** Uses `time.time()` (system clock) and `os.path.getmtime()` (filesystem mtime). Both are on the same container, so no clock skew issues.

## Implementation Order

1. **config.py** — add `PURGE_INTERVAL_SECONDS`
2. **app/purger.py** — new file: `_purge_all_sessions()`, `_purge_loop()`, `start_purge_thread()`
3. **app/worker.py** — call `start_purge_thread()` in `run_worker()`
4. **docker-compose.yml** — add `PURGE_INTERVAL_SECONDS=3600` to backend and worker
5. **Backend tests** — tests for `_purge_all_sessions()` with temp directories
6. **Run all tests, verify, git commit**

## Test Changes

### Add: backend/tests/test_purger.py

New test file for the purger module:

- `test_purge_all_sessions_deletes_old_files` — create temp session dir with old file, purge, verify deleted
- `test_purge_all_sessions_preserves_recent_files` — create temp session dir with fresh file, purge, verify kept
- `test_purge_all_sessions_removes_empty_session_dirs` — create temp session dir with only old files, purge, verify dir removed
- `test_purge_all_sessions_keeps_non_empty_session_dirs` — create temp session dir with old + fresh file, purge, verify dir stays (fresh file remains)
- `test_purge_all_sessions_clears_redis_mappings` — verify Redis mappings cleared for purged files
- `test_purge_all_sessions_clears_all_mappings_for_empty_session` — verify all Redis mappings cleared when session dir is emptied
- `test_purge_all_sessions_catches_orphaned_files` — file on disk with no Redis mapping, old -> deleted
- `test_purge_all_sessions_catches_orphaned_redis_mappings` — Redis mapping for file that doesn't exist on disk -> mapping cleared
- `test_purge_all_sessions_no_session_dir` — SESSION_DIR doesn't exist -> returns zeros, no crash
- `test_purge_all_sessions_skips_hidden_files` — `.gitkeep` etc. are not purged
- `test_start_purge_thread_starts_daemon` — verify thread is started and is a daemon
- `test_purge_loop_handles_exceptions` — mock _purge_all_sessions to raise, verify loop continues (doesn't crash)

### Mocking strategy
- Patch `SESSION_DIR` to a temp directory
- Mock Redis calls (`get_files_for_session`, `clear_file_for_session`, `clear_all_files_for_session`)
- Create real temp files with manipulated mtimes (`os.utime(path, (old_time, old_time))`)
- For the loop test, mock `time.sleep` to raise after first call to break the loop

## File Change Summary

| File | Change |
|------|--------|
| backend/app/core/config.py | +`PURGE_INTERVAL_SECONDS` config |
| backend/app/purger.py | NEW: `_purge_all_sessions()`, `_purge_loop()`, `start_purge_thread()` |
| backend/app/worker.py | +`start_purge_thread()` call in `run_worker()` |
| docker-compose.yml | +`PURGE_INTERVAL_SECONDS=3600` on backend + worker |
| backend/tests/test_purger.py | NEW: 12 tests for purge logic and thread startup |