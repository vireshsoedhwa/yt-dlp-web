"""
Tests for app.core.files_service — per-session file management.

Each session has its own directory under SESSION_DIR. yt-dlp downloads
directly into the session directory — no shared originals, no hard links.
Uses real temp directories and files.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


# --- get_session_file_path ---

def test_get_session_file_path_returns_safe_path(temp_downloads_dir):
    """get_session_file_path should return a path within the session directory."""
    from app.core.files_service import get_session_file_path
    path = get_session_file_path("test-session-123", "video.mp4")
    assert "test-session-123" in path
    assert path.endswith("video.mp4")


def test_get_session_file_path_rejects_bad_session_id(temp_downloads_dir):
    """get_session_file_path should reject session IDs with / or .."""
    from app.core.files_service import get_session_file_path
    with pytest.raises(ValueError):
        get_session_file_path("bad/session", "video.mp4")
    with pytest.raises(ValueError):
        get_session_file_path("..", "video.mp4")
    with pytest.raises(ValueError):
        get_session_file_path("foo..bar", "video.mp4")


def test_get_session_file_path_rejects_bad_filename(temp_downloads_dir):
    """get_session_file_path should reject filenames with / or .."""
    from app.core.files_service import get_session_file_path
    with pytest.raises(ValueError):
        get_session_file_path("test-session-123", "subdir/file.mp4")
    with pytest.raises(ValueError):
        get_session_file_path("test-session-123", "../etc/passwd")


# --- delete_session_file ---

def test_delete_session_file_removes_file(temp_downloads_dir):
    """delete_session_file should remove the file from the session directory."""
    from app.core.files_service import delete_session_file, get_session_file_path

    # Create a file in the session directory
    session_dir = os.path.join(temp_downloads_dir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    file_path = os.path.join(session_dir, "video.mp4")
    with open(file_path, "w") as f:
        f.write("test content")

    assert os.path.isfile(file_path)
    result = delete_session_file("test-session-123", "video.mp4")
    assert not os.path.isfile(file_path)
    assert result["file_was_deleted"] is True


def test_delete_session_file_cleans_up_empty_dir(temp_downloads_dir):
    """delete_session_file should remove the session directory if it becomes empty."""
    from app.core.files_service import delete_session_file

    session_dir = os.path.join(temp_downloads_dir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    file_path = os.path.join(session_dir, "video.mp4")
    with open(file_path, "w") as f:
        f.write("test content")

    result = delete_session_file("test-session-123", "video.mp4")
    assert result["session_dir_empty"] is True
    assert not os.path.isdir(session_dir)


def test_delete_session_file_keeps_dir_if_not_empty(temp_downloads_dir):
    """delete_session_file should keep the session directory if other files remain."""
    from app.core.files_service import delete_session_file

    session_dir = os.path.join(temp_downloads_dir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    # Create two files
    with open(os.path.join(session_dir, "video.mp4"), "w") as f:
        f.write("content1")
    with open(os.path.join(session_dir, "audio.webm"), "w") as f:
        f.write("content2")

    result = delete_session_file("test-session-123", "video.mp4")
    assert result["session_dir_empty"] is False
    assert os.path.isdir(session_dir)
    # Other file should still exist
    assert os.path.isfile(os.path.join(session_dir, "audio.webm"))


def test_delete_session_file_handles_missing_file(temp_downloads_dir):
    """delete_session_file should handle gracefully when the file doesn't exist."""
    from app.core.files_service import delete_session_file

    session_dir = os.path.join(temp_downloads_dir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)

    result = delete_session_file("test-session-123", "nonexistent.mp4")
    assert result["file_was_deleted"] is False
    # Directory should be empty -> cleaned up
    assert result["session_dir_empty"] is True


# --- file_exists_for_session ---

def test_file_exists_for_session_returns_true(temp_downloads_dir):
    """file_exists_for_session should return True when the file exists."""
    from app.core.files_service import file_exists_for_session

    session_dir = os.path.join(temp_downloads_dir, ".session", "session-1")
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "video.mp4"), "w") as f:
        f.write("content")

    assert file_exists_for_session("session-1", "video.mp4") is True


def test_file_exists_for_session_returns_false(temp_downloads_dir):
    """file_exists_for_session should return False when the file doesn't exist."""
    from app.core.files_service import file_exists_for_session
    assert file_exists_for_session("session-1", "nonexistent.mp4") is False


def test_file_exists_for_session_returns_false_for_bad_session(temp_downloads_dir):
    """file_exists_for_session should return False for invalid session IDs."""
    from app.core.files_service import file_exists_for_session
    assert file_exists_for_session("../etc", "passwd") is False


# --- get_file_size ---

def test_get_file_size_returns_bytes(temp_downloads_dir):
    """get_file_size should return the file size in bytes."""
    from app.core.files_service import get_file_size

    session_dir = os.path.join(temp_downloads_dir, ".session", "session-1")
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "video.mp4"), "w") as f:
        f.write("hello world")  # 11 bytes

    size = get_file_size("session-1", "video.mp4")
    assert size == 11


def test_get_file_size_returns_none_when_missing(temp_downloads_dir):
    """get_file_size should return None when the file doesn't exist."""
    from app.core.files_service import get_file_size
    assert get_file_size("session-1", "nonexistent.mp4") is None


def test_get_file_size_returns_none_for_bad_session(temp_downloads_dir):
    """get_file_size should return None for invalid session IDs."""
    from app.core.files_service import get_file_size
    assert get_file_size("../etc", "passwd") is None


# --- cleanup_session_dir ---

def test_cleanup_session_dir_removes_directory(temp_downloads_dir):
    """cleanup_session_dir should remove the session directory and all files."""
    from app.core.files_service import cleanup_session_dir

    session_dir = os.path.join(temp_downloads_dir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "video.mp4"), "w") as f:
        f.write("content")
    with open(os.path.join(session_dir, "audio.webm"), "w") as f:
        f.write("content")

    assert os.path.isdir(session_dir)
    cleanup_session_dir("test-session-123")
    assert not os.path.isdir(session_dir)


def test_cleanup_session_dir_handles_missing_dir(temp_downloads_dir):
    """cleanup_session_dir should not error when the directory doesn't exist."""
    from app.core.files_service import cleanup_session_dir
    # Should not raise
    cleanup_session_dir("nonexistent-session")