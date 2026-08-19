"""
File service -- manages per-session download files.

Each session has its own directory under SESSION_DIR. yt-dlp downloads
directly into the session directory — no shared originals, no hard links.
When the user downloads a file, it is served from the session directory
and then deleted. Empty session directories are cleaned up automatically.
"""

import os
import shutil

from app.core.config import SESSION_DIR


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
    """Return the full path to a file in the session's directory."""
    _validate_session_id(session_id)

    # Sanitize filename (same protection as files API)
    if not filename or not filename.strip():
        raise ValueError("Invalid filename")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Invalid filename")

    return os.path.join(SESSION_DIR, session_id, os.path.basename(filename))


def delete_session_file(session_id: str, filename: str) -> dict:
    """
    Delete a file from the session's directory.

    After deletion, if the session directory is empty, it is removed.

    Returns:
        {"deleted": filename, "session_dir_empty": bool}
    """
    _validate_session_id(session_id)

    file_path = get_session_file_path(session_id, filename)
    deleted = False

    if os.path.isfile(file_path):
        os.remove(file_path)
        deleted = True

    # Clean up empty session directory
    session_dir = get_session_dir(session_id)
    session_dir_empty = False
    if os.path.isdir(session_dir):
        try:
            if not os.listdir(session_dir):
                os.rmdir(session_dir)
                session_dir_empty = True
        except OSError:
            pass  # Directory not empty or other error -- ignore

    return {
        "deleted": filename,
        "session_dir_empty": session_dir_empty,
        "file_was_deleted": deleted,
    }


def file_exists_for_session(session_id: str, filename: str) -> bool:
    """Check if a file exists in the session's directory."""
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
    Remove a session's entire directory and all its files.
    Called during purge or session cleanup.
    """
    _validate_session_id(session_id)
    session_dir = get_session_dir(session_id)

    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)