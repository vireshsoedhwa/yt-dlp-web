"""
Tests for app.purger — background purge scheduler.

Tests use real temp directories with files that have manipulated mtimes
to simulate old and new files. Redis calls are mocked.
"""

import os
import time
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from threading import Event

from app.purger import _purge_all_sessions, start_purge_thread


def _make_old_file(path: str, age_hours: float = 5.0) -> None:
    """Create a file and set its mtime to age_hours ago."""
    with open(path, "w") as f:
        f.write("fake content")
    old_time = time.time() - (age_hours * 3600)
    os.utime(path, (old_time, old_time))


def _make_recent_file(path: str) -> None:
    """Create a file with current mtime (recent)."""
    with open(path, "w") as f:
        f.write("fake content")


def _setup_session_dir(base_dir: str, session_id: str) -> str:
    """Create a session directory under base_dir/.session/ and return its path."""
    session_path = os.path.join(base_dir, ".session", session_id)
    os.makedirs(session_path, exist_ok=True)
    return session_path


# --- _purge_all_sessions ---

def test_purge_deletes_old_files():
    """_purge_all_sessions should delete files older than max_age_hours."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        old_file = os.path.join(session_path, "old_video.mp4")
        _make_old_file(old_file, age_hours=5.0)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["old_video.mp4"]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        assert result["files_purged"] == 1
        assert not os.path.isfile(old_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_preserves_recent_files():
    """_purge_all_sessions should NOT delete files newer than max_age_hours."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        recent_file = os.path.join(session_path, "new_video.mp4")
        _make_recent_file(recent_file)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["new_video.mp4"]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        assert result["files_purged"] == 0
        assert os.path.isfile(recent_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_removes_empty_session_dirs():
    """_purge_all_sessions should remove empty session directories after purging."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        old_file = os.path.join(session_path, "old_video.mp4")
        _make_old_file(old_file, age_hours=5.0)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["old_video.mp4"]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            _purge_all_sessions(max_age_hours=3)

        assert not os.path.isdir(session_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_keeps_non_empty_session_dirs():
    """_purge_all_sessions should keep session dirs that still have files."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        old_file = os.path.join(session_path, "old_video.mp4")
        recent_file = os.path.join(session_path, "new_video.mp4")
        _make_old_file(old_file, age_hours=5.0)
        _make_recent_file(recent_file)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["old_video.mp4", "new_video.mp4"]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            _purge_all_sessions(max_age_hours=3)

        assert os.path.isdir(session_path)
        assert os.path.isfile(recent_file)
        assert not os.path.isfile(old_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_clears_redis_mappings():
    """_purge_all_sessions should clear Redis file mappings for purged files."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        old_file = os.path.join(session_path, "old_video.mp4")
        _make_old_file(old_file, age_hours=5.0)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["old_video.mp4"]), \
             patch("app.purger.clear_file_for_session") as mock_clear_file, \
             patch("app.purger.clear_all_files_for_session") as mock_clear_all_files, \
             patch("app.purger.clear_all_jobs_for_session") as mock_clear_jobs:
            _purge_all_sessions(max_age_hours=3)

        mock_clear_file.assert_called_once_with("sess-1", "old_video.mp4")
        mock_clear_all_files.assert_called_once_with("sess-1")
        mock_clear_jobs.assert_called_once_with("sess-1")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_catches_orphaned_files():
    """_purge_all_sessions should delete old files on disk even without Redis mapping."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        orphan_file = os.path.join(session_path, "orphan.mp4")
        _make_old_file(orphan_file, age_hours=5.0)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=[]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        assert result["files_purged"] == 1
        assert not os.path.isfile(orphan_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_catches_orphaned_redis_mappings():
    """_purge_all_sessions should clear Redis mappings for files that don't exist on disk."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        # No file on disk, but Redis says it exists
        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=["ghost.mp4"]), \
             patch("app.purger.clear_file_for_session") as mock_clear, \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        assert result["files_purged"] == 0
        mock_clear.assert_called_once_with("sess-1", "ghost.mp4")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_no_session_dir():
    """_purge_all_sessions should return zeros when SESSION_DIR doesn't exist."""
    with patch("app.purger.SESSION_DIR", "/nonexistent/path"):
        result = _purge_all_sessions(max_age_hours=3)

    assert result["sessions_scanned"] == 0
    assert result["files_purged"] == 0
    assert result["freed_bytes"] == 0


def test_purge_skips_hidden_files():
    """_purge_all_sessions should skip hidden files (dotfiles)."""
    tmpdir = tempfile.mkdtemp()
    try:
        session_path = _setup_session_dir(tmpdir, "sess-1")
        # Create a hidden file that's old
        hidden_file = os.path.join(session_path, ".hidden")
        _make_old_file(hidden_file, age_hours=5.0)

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=[]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        # Hidden file should NOT be counted as purged
        assert result["files_purged"] == 0
        # But the session dir stays because the hidden file remains
        assert os.path.isdir(session_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_purge_multiple_sessions():
    """_purge_all_sessions should scan multiple session directories."""
    tmpdir = tempfile.mkdtemp()
    try:
        _setup_session_dir(tmpdir, "sess-1")
        _setup_session_dir(tmpdir, "sess-2")
        _setup_session_dir(tmpdir, "sess-3")

        with patch("app.purger.SESSION_DIR", os.path.join(tmpdir, ".session")), \
             patch("app.purger.get_files_for_session", return_value=[]), \
             patch("app.purger.clear_file_for_session"), \
             patch("app.purger.clear_all_files_for_session"), \
             patch("app.purger.clear_all_jobs_for_session"):
            result = _purge_all_sessions(max_age_hours=3)

        assert result["sessions_scanned"] == 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- start_purge_thread ---

def test_start_purge_thread_starts_daemon():
    """start_purge_thread should start a daemon thread."""
    with patch("app.purger._purge_loop"):
        thread = start_purge_thread()
        assert thread.daemon is True
        assert thread.name == "purger"
        # Clean up — join won't work on infinite loop, but daemon=True means
        # it dies with the process. We can't easily stop it, but since
        # _purge_loop is patched (no-op), the thread will return immediately.


def test_purge_loop_handles_exceptions():
    """_purge_loop should continue after an exception, not crash."""
    call_count = [0]
    stop = Event()

    def fake_purge(max_age):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Simulated failure")
        # Second call stops the loop
        stop.set()

    def fake_sleep(seconds):
        if stop.is_set():
            raise SystemExit()  # Break out of the loop

    with patch("app.purger._purge_all_sessions", side_effect=fake_purge), \
         patch("app.purger.time.sleep", side_effect=fake_sleep), \
         patch("app.purger.PURGE_INTERVAL_SECONDS", 0), \
         patch("app.purger.PURGE_MAX_AGE_HOURS", 3):
        try:
            from app.purger import _purge_loop
            _purge_loop()
        except SystemExit:
            pass

    # First call raised, but the loop continued and called again
    assert call_count[0] >= 2