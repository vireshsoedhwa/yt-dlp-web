"""
Tests for app.api.files — GET /api/files (list), GET /api/files/{filename} (download),
POST /api/purge, GET /api/purge/preview.

Mocks the filesystem and Redis session functions so no real files or Redis are needed.
Path traversal protection is tested at the _safe_filename function level.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SESSION_HEADERS = {"X-Session-ID": "test-session-123"}


# --- _safe_filename unit tests ---

def test_safe_path_rejects_dotdot():
    """_safe_filename should reject filenames containing .."""
    from app.api.files import _safe_filename
    with pytest.raises(Exception) as exc_info:
        _safe_filename("../../etc/passwd")
    assert "Invalid" in str(exc_info.value)


def test_safe_path_rejects_slash():
    """_safe_filename should reject filenames containing /"""
    from app.api.files import _safe_filename
    with pytest.raises(Exception) as exc_info:
        _safe_filename("subdir/file.mp4")
    assert "Invalid" in str(exc_info.value)


def test_safe_path_rejects_backslash():
    """_safe_filename should reject filenames containing backslash"""
    from app.api.files import _safe_filename
    with pytest.raises(Exception) as exc_info:
        _safe_filename("..\\secret.txt")
    assert "Invalid" in str(exc_info.value)


def test_safe_path_rejects_empty():
    """_safe_filename should reject empty filenames"""
    from app.api.files import _safe_filename
    with pytest.raises(Exception):
        _safe_filename("")


def test_safe_path_accepts_normal_filename():
    """_safe_filename should accept a normal filename and return it"""
    from app.api.files import _safe_filename
    result = _safe_filename("video.mp4")
    assert result == "video.mp4"


# --- GET /api/files ---

def test_list_files_returns_400_without_session_header():
    """GET /api/files without X-Session-ID header should return 400."""
    response = client.get("/api/files")
    assert response.status_code == 400


def test_list_files_returns_empty_for_session():
    """GET /api/files should return empty list when session has no files."""
    with patch("app.api.files.get_files_for_session", return_value=[]):
        response = client.get("/api/files", headers=SESSION_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"files": []}


def test_list_files_returns_files_for_session():
    """GET /api/files should return files registered to the session."""
    with patch("app.api.files.get_files_for_session", return_value=["video.mp4", "audio.webm"]), \
         patch("app.api.files.get_file_size", side_effect=[1024, 2048]):
        response = client.get("/api/files", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 2
    filenames = [f["filename"] for f in data["files"]]
    assert "video.mp4" in filenames
    assert "audio.webm" in filenames
    for f in data["files"]:
        assert "size_bytes" in f
        assert "size_mb" in f


# --- GET /api/files/{filename} ---

def test_download_file_returns_400_without_session_header():
    """GET /api/files/{filename} without X-Session-ID should return 400."""
    response = client.get("/api/files/video.mp4")
    assert response.status_code == 400


def test_download_file_returns_403_for_wrong_session():
    """GET /api/files/{filename} should return 403 when file doesn't belong to session."""
    with patch("app.core.queue.file_belongs_to_session", return_value=False):
        response = client.get("/api/files/video.mp4", headers=SESSION_HEADERS)
    assert response.status_code == 403


def test_download_file_rejects_backslash():
    """GET /api/files with backslash in filename should be rejected with 400."""
    response = client.get("/api/files/..%5Csecret.txt", headers=SESSION_HEADERS)
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_download_file_success():
    """GET /api/files/{filename} should return the file when it belongs to the session."""
    tmpdir = tempfile.mkdtemp()
    session_dir = os.path.join(tmpdir, ".session", "test-session-123")
    os.makedirs(session_dir, exist_ok=True)

    # Create the session file
    session_file = os.path.join(session_dir, "test_video.mp4")
    with open(session_file, "w") as f:
        f.write("test content")

    try:
        with patch("app.core.queue.file_belongs_to_session", return_value=True), \
             patch("app.api.files.file_exists_for_session", return_value=True), \
             patch("app.api.files.get_session_file_path", return_value=session_file), \
             patch("app.api.files.delete_session_file") as mock_delete, \
             patch("app.api.files.clear_file_for_session") as mock_clear:
            response = client.get("/api/files/test_video.mp4", headers=SESSION_HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        # Verify the background cleanup task was executed (TestClient runs
        # background tasks synchronously after the response)
        mock_delete.assert_called_once_with("test-session-123", "test_video.mp4")
        mock_clear.assert_called_once_with("test-session-123", "test_video.mp4")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_download_file_not_found():
    """GET /api/files/{filename} for non-existent file should return 404."""
    with patch("app.core.queue.file_belongs_to_session", return_value=True), \
         patch("app.api.files.file_exists_for_session", return_value=False), \
         patch("app.api.files.create_session_link", return_value=None):
        response = client.get("/api/files/nonexistent.mp4", headers=SESSION_HEADERS)

    assert response.status_code == 404


# --- POST /api/purge ---

def test_purge_endpoint_registered():
    """POST /api/purge should resolve (400 for missing session header = route exists)."""
    response = client.post("/api/purge")
    assert response.status_code == 400  # Missing session header, but route exists


def test_purge_returns_400_without_session_header():
    """POST /api/purge without X-Session-ID should return 400."""
    response = client.post("/api/purge")
    assert response.status_code == 400


# --- GET /api/purge/preview ---

def test_purge_preview_endpoint_registered():
    """GET /api/purge/preview should resolve (400 for missing session header = route exists)."""
    response = client.get("/api/purge/preview")
    assert response.status_code == 400  # Missing session header, but route exists