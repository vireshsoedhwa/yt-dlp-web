"""
Shared test fixtures — fake Redis, fake RQ queue, fake yt-dlp.

These let every test run without Docker, Redis, or network access.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.core.queue import _redis_conn


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Reset the Redis connection singleton between tests."""
    import app.core.queue as queue_mod
    queue_mod._redis_conn = None
    yield
    queue_mod._redis_conn = None


@pytest.fixture
def fake_redis():
    """Return a MagicMock that behaves like a Redis connection."""
    redis = MagicMock()
    redis.from_url.return_value = redis
    with patch("app.core.queue.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = redis
        yield redis


@pytest.fixture
def fake_queue(fake_redis):
    """Return a MagicMock that behaves like an RQ Queue."""
    queue = MagicMock()
    with patch("app.core.queue.Queue") as mock_queue_cls:
        mock_queue_cls.return_value = queue
        yield queue


@pytest.fixture
def fake_job():
    """Return a fake RQ Job with realistic fields."""
    job = MagicMock()
    job.id = "abc12345"
    job.get_status.return_value = "finished"
    job.kwargs = {"url": "https://example.com/video", "session_id": "test-session-123"}
    job.result = {
        "status": "completed",
        "url": "https://example.com/video",
        "format": "best",
        "files": ["Test Video [abc123].mp4"],
        "session_id": "test-session-123",
    }
    job.exc_info = None
    job.enqueued_at = datetime(2025, 1, 1, 12, 0, 0)
    job.started_at = datetime(2025, 1, 1, 12, 0, 5)
    job.ended_at = datetime(2025, 1, 1, 12, 1, 0)
    return job


@pytest.fixture
def fake_yt_info():
    """Return fake yt-dlp metadata as returned by extract_info."""
    return {
        "title": "Test Video",
        "uploader": "Test Channel",
        "duration": 120,
        "thumbnail": "https://example.com/thumb.jpg",
        "formats": [
            {"format_id": "137", "ext": "mp4", "resolution": "1080p"},
            {"format_id": "251", "ext": "webm", "resolution": "audio only"},
        ],
    }


@pytest.fixture
def fake_session_id():
    """Return a fake session ID for testing."""
    return "test-session-123"


@pytest.fixture
def temp_downloads_dir():
    """Create a temp directory with .session/ subdirectory, patch DOWNLOAD_DIR and SESSION_DIR.

    Yields the path to the temp downloads directory.
    Cleans up after the test.
    """
    tmpdir = tempfile.mkdtemp(prefix="ytdlp_test_")
    session_dir = os.path.join(tmpdir, ".session")
    os.makedirs(session_dir, exist_ok=True)

    with patch("app.core.config.DOWNLOAD_DIR", tmpdir) as _cfg_dd, \
         patch("app.core.config.SESSION_DIR", session_dir) as _cfg_sd, \
         patch("app.core.files_service.DOWNLOAD_DIR", tmpdir) as _fs_dd, \
         patch("app.core.files_service.SESSION_DIR", session_dir) as _fs_sd, \
         patch("app.core.yt_dlp_service.DOWNLOAD_DIR", tmpdir) as _yd_dd, \
         patch("app.api.files.DOWNLOAD_DIR", tmpdir) as _api_dd:
        yield tmpdir

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)