"""
File serving endpoint — serve downloaded files to the user with session isolation.

GET  /api/files              — list files for the current session
GET  /api/files/{filename}   — download a file (serve-then-delete via hard link)
POST /api/purge              — delete old files for the current session
GET  /api/purge/preview      — preview what would be purged

Security:
- Filenames are sanitized to prevent path traversal (no /, \, ..)
- Session ID is required (X-Session-ID header)
- Files are only served to the session that owns them
- Hard links isolate sessions — deleting one session's file doesn't affect others
"""

import os
import time
from typing import Annotated
from fastapi import APIRouter, HTTPException, Header, BackgroundTasks
from fastapi.responses import FileResponse

from app.core.config import DOWNLOAD_DIR, PURGE_MAX_AGE_HOURS
from app.core.queue import (
    get_files_for_session,
    clear_file_for_session,
    clear_active_job_for_url,
)
from app.core.files_service import (
    get_session_file_path,
    create_session_link,
    delete_session_file,
    file_exists_for_session,
    get_file_size,
    get_original_path,
)
from app.core.yt_dlp_service import parse_video_id, remove_from_archive

router = APIRouter()

# Files to skip during purge (never delete these)
_SKIP_FILES = {".ytdlp-archive.txt", ".gitkeep"}


def _safe_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal. Returns basename."""
    if not filename or not filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    basename = os.path.basename(filename)
    if basename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return basename


def _require_session(x_session_id: str | None) -> str:
    """Extract and validate the X-Session-ID header. Raises 400 if missing."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")
    return x_session_id


# --- GET /api/files ---

@router.get("/files")
def list_files(x_session_id: str | None = Header(None)):
    """List files belonging to the current session."""
    session_id = _require_session(x_session_id)
    filenames = get_files_for_session(session_id)

    files = []
    for name in filenames:
        size = get_file_size(session_id, name)
        if size is not None:
            files.append({
                "filename": name,
                "size_bytes": size,
                "size_mb": round(size / (1024 * 1024), 2),
            })

    return {"files": files}


# --- GET /api/files/{filename} ---

@router.get("/files/{filename}")
def download_file(
    filename: str,
    background_tasks: Annotated[BackgroundTasks, BackgroundTasks()],
    x_session_id: str | None = Header(None),
):
    """Download a file. The session's hard link is deleted after serving."""
    session_id = _require_session(x_session_id)
    basename = _safe_filename(filename)

    # Check file belongs to this session
    from app.core.queue import file_belongs_to_session
    if not file_belongs_to_session(session_id, basename):
        raise HTTPException(status_code=403, detail="File does not belong to this session")

    # If the session doesn't have a hard link yet but the original exists,
    # create one on the fly (handles dedup: second session downloading same video)
    if not file_exists_for_session(session_id, basename):
        link_path = create_session_link(session_id, basename)
        if link_path is None:
            # Original file was already deleted by another session's cleanup
            raise HTTPException(status_code=404, detail="File no longer available, please re-download")
        # Register the file to this session
        from app.core.queue import register_file_for_session
        register_file_for_session(session_id, basename)

    session_path = get_session_file_path(session_id, basename)
    if not os.path.isfile(session_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Schedule cleanup after the response is sent.
    # The background task deletes the session's hard link. If that was the
    # last link (st_nlink == 1 after removal), the original file is also
    # deleted and the archive entry is removed.
    def _cleanup():
        result = delete_session_file(session_id, basename)
        clear_file_for_session(session_id, basename)

    background_tasks.add_task(_cleanup)

    return FileResponse(
        session_path,
        filename=basename,
        media_type="application/octet-stream",
    )


# --- POST /api/purge ---

@router.post("/purge")
def purge_files(x_session_id: str | None = Header(None)):
    """Delete files older than PURGE_MAX_AGE_HOURS for the current session."""
    session_id = _require_session(x_session_id)
    result = _purge_old_files(session_id, PURGE_MAX_AGE_HOURS, delete=True)
    return result


# --- GET /api/purge/preview ---

@router.get("/purge/preview")
def purge_preview(x_session_id: str | None = Header(None)):
    """Preview which files would be purged for the current session."""
    session_id = _require_session(x_session_id)
    result = _purge_old_files(session_id, PURGE_MAX_AGE_HOURS, delete=False)
    return result


# --- Purge logic ---

def _purge_old_files(session_id: str, max_age_hours: int, delete: bool) -> dict:
    """
    Core purge logic shared by purge and preview endpoints.

    Purges:
    1. Session files (hard links) older than max_age_hours
    2. Orphaned original files (st_nlink == 1, no session links) older than max_age_hours

    Returns: {"purged": [...], "skipped": N, "freed_bytes": N}
    """
    max_age_seconds = max_age_hours * 3600
    now = time.time()

    purged = []
    freed_bytes = 0
    skipped = 0

    # 1. Purge session files
    filenames = get_files_for_session(session_id)
    for name in filenames:
        try:
            session_path = get_session_file_path(session_id, name)
        except ValueError:
            skipped += 1
            continue

        if not os.path.isfile(session_path):
            # File already gone -- just clean up the Redis mapping
            if delete:
                clear_file_for_session(session_id, name)
            skipped += 1
            continue

        file_mtime = os.path.getmtime(session_path)
        age_seconds = now - file_mtime

        if age_seconds < max_age_seconds:
            skipped += 1
            continue

        size = os.path.getsize(session_path)
        video_id = parse_video_id(name)

        if delete:
            result = delete_session_file(session_id, name)
            clear_file_for_session(session_id, name)
            freed_bytes += size

        purged.append({
            "filename": name,
            "video_id": video_id,
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2),
            "age_hours": round(age_seconds / 3600, 2),
        })

    # 2. Purge orphaned originals (no session links, old)
    if delete and os.path.isdir(DOWNLOAD_DIR):
        for name in os.listdir(DOWNLOAD_DIR):
            # Skip hidden files, archive, gitkeep, session dir
            if name.startswith(".") or name in _SKIP_FILES:
                continue

            filepath = os.path.join(DOWNLOAD_DIR, name)
            if not os.path.isfile(filepath):
                continue

            file_mtime = os.path.getmtime(filepath)
            age_seconds = now - file_mtime

            if age_seconds < max_age_seconds:
                continue

            # Check if orphaned (only 1 link = the original itself)
            stat = os.stat(filepath)
            if stat.st_nlink <= 1:
                size = os.path.getsize(filepath)
                video_id = parse_video_id(name)

                os.remove(filepath)
                if video_id:
                    remove_from_archive(video_id)
                freed_bytes += size

                purged.append({
                    "filename": name,
                    "video_id": video_id,
                    "size_bytes": size,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "age_hours": round(age_seconds / 3600, 2),
                    "orphaned": True,
                })

    return {
        "purged": purged,
        "skipped": skipped,
        "freed_bytes": freed_bytes,
    }