"""
Tests for app.core.files_service — per-session hard link management.

Uses real temp directories and files to test hard link behavior.
All tests use the temp_downloads_dir fixture which patches DOWNLOAD_DIR and SESSION_DIR.
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
    """get_session_file_path should reject filenames with /"""
    from app.core.files_service import get_session_file_path
    with pytest.raises(ValueError):
        get_session_file_path("test-session-123", "subdir/file.mp4")


# --- create_session_link ---

def test_create_session_link_creates_hard_link(temp_downloads_dir):
    """create_session_link should create a hard link with the same inode."""
    from app.core.files_service import create_session_link

    # Create an original file in DOWNLOAD_DIR
    original_path = os.path.join(temp_downloads_dir, "video.mp4")
    with open(original_path, "w") as f:
        f.write("test content")

    link_path = create_session_link("test-session-123", "video.mp4")

    assert link_path is not None
    assert os.path.isfile(link_path)
    assert os.path.isfile(original_path)
    # Same inode = hard link
    assert os.stat(link_path).st_ino == os.stat(original_path).st_ino


def test_create_session_link_returns_none_when_original_missing(temp_downloads_dir):
    """create_session_link should return None when original file doesn't exist."""
    from app.core.files_service import create_session_link
    result = create_session_link("test-session-123", "nonexistent.mp4")
    assert result is None


# --- delete_session_file ---

def test_delete_session_file_removes_link_only(temp_downloads_dir):
    """When multiple links exist, deleting one should not delete the original."""
    from app.core.files_service import create_session_link, delete_session_file

    # Create original file
    original_path = os.path.join(temp_downloads_dir, "video.mp4")
    with open(original_path, "w") as f:
        f.write("test content")

    # Create two session links
    create_session_link("session-1", "video.mp4")
    create_session_link("session-2", "video.mp4")

    # Original + 2 links = 3 links
    assert os.stat(original_path).st_nlink == 3

    # Delete one session's link
    result = delete_session_file("session-1", "video.mp4")

    assert result["session_link_deleted"] is True
    # Original should still exist
    assert os.path.isfile(original_path)
    # st_nlink should have decremented
    assert os.stat(original_path).st_nlink == 2
    assert not result["original_removed"]


def test_delete_session_file_removes_original_when_last_link(temp_downloads_dir):
    """When the last session link is deleted, the original should also be deleted."""
    from app.core.files_service import create_session_link, delete_session_file

    # Create original file
    original_path = os.path.join(temp_downloads_dir, "video.mp4")
    with open(original_path, "w") as f:
        f.write("test content")

    # Create one session link
    create_session_link("session-1", "video.mp4")

    # Original + 1 link = 2 links
    assert os.stat(original_path).st_nlink == 2

    # Delete the session link
    result = delete_session_file("session-1", "video.mp4")

    assert result["session_link_deleted"] is True
    assert result["original_removed"] is True
    # Original should be gone
    assert not os.path.isfile(original_path)


def test_delete_session_file_removes_archive_when_original_removed(temp_downloads_dir):
    """When the original is removed, remove_from_archive should be called with the video ID."""
    from app.core.files_service import create_session_link, delete_session_file

    # Create original file with a name that has a video ID
    filename = "Test Video [abc123].mp4"
    original_path = os.path.join(temp_downloads_dir, filename)
    with open(original_path, "w") as f:
        f.write("test content")

    create_session_link("session-1", filename)

    with patch("app.core.yt_dlp_service.remove_from_archive") as mock_remove:
        result = delete_session_file("session-1", filename)

    # Original should be removed (only 1 link after session link deletion)
    assert result["original_removed"] is True
    assert result["video_id"] == "abc123"
    # remove_from_archive should have been called with the video_id
    mock_remove.assert_called_once_with("abc123")


# --- file_exists_for_session ---

def test_file_exists_for_session_returns_true(temp_downloads_dir):
    """file_exists_for_session should return True when the session link exists."""
    from app.core.files_service import create_session_link, file_exists_for_session

    filename = "video.mp4"
    original_path = os.path.join(temp_downloads_dir, filename)
    with open(original_path, "w") as f:
        f.write("test content")

    create_session_link("session-1", filename)

    assert file_exists_for_session("session-1", filename) is True


def test_file_exists_for_session_returns_false(temp_downloads_dir):
    """file_exists_for_session should return False when the session link doesn't exist."""
    from app.core.files_service import file_exists_for_session
    assert file_exists_for_session("session-1", "nonexistent.mp4") is False


# --- get_file_size ---

def test_get_file_size_returns_bytes(temp_downloads_dir):
    """get_file_size should return the file size in bytes."""
    from app.core.files_service import create_session_link, get_file_size

    filename = "video.mp4"
    original_path = os.path.join(temp_downloads_dir, filename)
    with open(original_path, "w") as f:
        f.write("hello world")  # 11 bytes

    create_session_link("session-1", filename)

    size = get_file_size("session-1", filename)
    assert size == 11


def test_get_file_size_returns_none_when_missing(temp_downloads_dir):
    """get_file_size should return None when the file doesn't exist."""
    from app.core.files_service import get_file_size
    assert get_file_size("session-1", "nonexistent.mp4") is None