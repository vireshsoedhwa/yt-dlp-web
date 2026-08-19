"""
File service -- manages per-session hard links to downloaded files.

When yt-dlp downloads a video, the original file lands in DOWNLOAD_DIR.
This module creates hard links in a per-session subdirectory so that:
- Each session has its own file handle (isolation)
- Multiple sessions sharing the same video each get their own link
- Deleting one session's link does NOT delete the underlying data
- The original is only deleted when the last link is removed (st_nlink == 1)
- The filesystem handles reference counting automatically via inode link counts
"""

import os
import shutil

from app.core.config import DOWNLOAD_DIR, SESSION_DIR


def _validate_session_id(session_id: str) -> None:
    """Validate that a session ID is safe (UUID format, no path traversal)."""
    if not session_id or not session_id.strip():
        raise ValueError("Invalid session ID")

    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise ValueError("Invalid session ID")

    basename = os.path.basename(session_id)
    if basename != session_id:
        raise ValueError("Invalid session ID")


def get_session_dir(session_id: str) -> str:
    """Return the directory path for a session's files."""
    _validate_session_id(session_id)
    return os.path.join(SESSION_DIR, session_id)


def get_session_file_path(session_id: str, filename: str) -> str:
    """Return the full path to a session-specific hard link."""
    _validate_session_id(session_id)

    # Sanitize filename (same protection as files API)
    if not filename or not filename.strip():
        raise ValueError("Invalid filename")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Invalid filename")

    return os.path.join(SESSION_DIR, session_id, os.path.basename(filename))


def get_original_path(filename: str) -> str:
    """Return the path to the original downloaded file in DOWNLOAD_DIR."""
    basename = os.path.basename(filename)
    if "/" in basename or "\\" in basename or ".." in basename:
        raise ValueError("Invalid filename")
    return os.path.join(DOWNLOAD_DIR, basename)


def create_session_link(session_id: str, filename: str) -> str | None:
    """
    Create a hard link from the original file to a session-specific path.

    Returns the session file path on success, None if the original file
    doesn't exist (already deleted by another session's cleanup).
    """
    original = get_original_path(filename)

    # If the original doesn't exist, we can't create a link
    if not os.path.isfile(original):
        return None

    session_path = get_session_file_path(session_id, filename)

    # Create session directory if needed
    session_dir = os.path.dirname(session_path)
    os.makedirs(session_dir, exist_ok=True)

    # Create hard link (overwrite if already exists)
    if os.path.exists(session_path):
        os.remove(session_path)
    os.link(original, session_path)

    return session_path


def delete_session_file(session_id: str, filename: str) -> dict:
    """
    Delete a session's hard link and potentially the original file.

    After deleting the session link, checks the original file's link count.
    If st_nlink == 1 (only the original remains, no other session links),
    the original is also deleted and the video ID is removed from the archive.

    Returns:
        {"deleted": filename, "original_removed": bool, "video_id": str | None}
    """
    from app.core.yt_dlp_service import parse_video_id, remove_from_archive

    session_path = get_session_file_path(session_id, filename)
    original = get_original_path(filename)

    deleted_session_link = False

    # Delete the session's hard link
    if os.path.exists(session_path):
        os.remove(session_path)
        deleted_session_link = True

    # Check if the original should also be deleted
    original_removed = False
    video_id = parse_video_id(filename)

    if os.path.isfile(original):
        stat = os.stat(original)
        # st_nlink counts all hard links including the original itself.
        # If st_nlink == 1, only the original file entry remains (no session links).
        if stat.st_nlink <= 1:
            os.remove(original)
            original_removed = True
            if video_id:
                remove_from_archive(video_id)

    # Clean up empty session directory
    session_dir = os.path.dirname(session_path)
    if os.path.isdir(session_dir):
        try:
            if not os.listdir(session_dir):
                os.rmdir(session_dir)
        except OSError:
            pass  # Directory not empty or other error -- ignore

    return {
        "deleted": filename,
        "original_removed": original_removed,
        "video_id": video_id,
        "session_link_deleted": deleted_session_link,
    }


def file_exists_for_session(session_id: str, filename: str) -> bool:
    """Check if a session-specific hard link exists on disk."""
    try:
        path = get_session_file_path(session_id, filename)
        return os.path.isfile(path)
    except ValueError:
        return False


def get_file_size(session_id: str, filename: str) -> int | None:
    """Return file size in bytes for a session's file, None if it doesn't exist."""
    try:
        path = get_session_file_path(session_id, filename)
        if not os.path.isfile(path):
            return None
        return os.path.getsize(path)
    except ValueError:
        return None


def cleanup_session_dir(session_id: str) -> None:
    """
    Remove a session's entire directory and all its hard links.
    Called during purge or session cleanup.
    """
    _validate_session_id(session_id)
    session_dir = get_session_dir(session_id)

    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)