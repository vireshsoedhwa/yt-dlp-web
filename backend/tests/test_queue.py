"""
Tests for app.core.queue — Redis connection, Queue helpers,
dedup helpers, and session-to-file mapping helpers.

Mocks Redis and RQ Queue so no Redis server is needed.
"""

from unittest.mock import patch, MagicMock


def test_get_redis_creates_connection_once(fake_redis):
    """get_redis should create a Redis connection from REDIS_URL."""
    with patch("app.core.queue.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = fake_redis
        from app.core.queue import get_redis
        conn1 = get_redis()
        conn2 = get_redis()

    # Singleton — same instance returned
    assert conn1 is conn2
    mock_redis_cls.from_url.assert_called_once()


def test_get_redis_uses_redis_url():
    """get_redis should pass REDIS_URL to Redis.from_url."""
    with patch("app.core.queue.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        from app.core.queue import get_redis
        get_redis()

    call_args = mock_redis_cls.from_url.call_args[0][0]
    assert call_args.startswith("redis://")


def test_get_queue_returns_queue_with_name():
    """get_queue should return a Queue named 'downloads'."""
    with patch("app.core.queue.Redis") as mock_redis_cls, \
         patch("app.core.queue.Queue") as mock_queue_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        mock_queue_cls.return_value = MagicMock()
        from app.core.queue import get_queue
        queue = get_queue()

    # Queue should be instantiated with QUEUE_NAME
    assert mock_queue_cls.called
    args = mock_queue_cls.call_args
    assert args[0][0] == "downloads"  # positional arg = queue name


def test_get_queue_reuses_redis_connection():
    """get_queue should reuse the shared Redis connection."""
    with patch("app.core.queue.Redis") as mock_redis_cls, \
         patch("app.core.queue.Queue") as mock_queue_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        mock_queue_cls.return_value = MagicMock()
        from app.core.queue import get_redis, get_queue
        conn = get_redis()
        get_queue()

    # Queue should receive the same connection object
    queue_kwargs = mock_queue_cls.call_args[1]
    assert queue_kwargs["connection"] is conn


# --- Dedup helpers (URL-to-job mapping) ---

def test_url_hash_is_deterministic():
    """_url_hash should return the same hash for the same URL."""
    from app.core.queue import _url_hash
    h1 = _url_hash("https://example.com/video")
    h2 = _url_hash("https://example.com/video")
    assert h1 == h2


def test_url_hash_is_different_for_different_urls():
    """_url_hash should return different hashes for different URLs."""
    from app.core.queue import _url_hash
    h1 = _url_hash("https://example.com/video1")
    h2 = _url_hash("https://example.com/video2")
    assert h1 != h2


def test_get_active_job_for_url_returns_none_when_empty(fake_redis):
    """get_active_job_for_url should return None when no mapping exists."""
    fake_redis.get.return_value = None
    from app.core.queue import get_active_job_for_url
    result = get_active_job_for_url("https://example.com/video")
    assert result is None
    fake_redis.get.assert_called_once()


def test_set_then_get_active_job_for_url(fake_redis):
    """set_active_job_for_url then get_active_job_for_url should return the job_id."""
    fake_redis.setex.return_value = True
    fake_redis.get.return_value = b"job-123"

    from app.core.queue import set_active_job_for_url, get_active_job_for_url

    set_active_job_for_url("https://example.com/video", "job-123")
    result = get_active_job_for_url("https://example.com/video")

    assert result == "job-123"


def test_clear_active_job_for_url(fake_redis):
    """clear_active_job_for_url should call redis.delete."""
    fake_redis.delete.return_value = 1
    from app.core.queue import clear_active_job_for_url
    clear_active_job_for_url("https://example.com/video")
    fake_redis.delete.assert_called_once()


def test_set_active_job_for_url_sets_ttl(fake_redis):
    """set_active_job_for_url should call setex with TTL."""
    from app.core.queue import set_active_job_for_url
    set_active_job_for_url("https://example.com/video", "job-123")

    fake_redis.setex.assert_called_once()
    args = fake_redis.setex.call_args[0]
    # args: (key, ttl, value)
    assert args[1] == 3600  # DEDUP_TTL_SECONDS default
    assert args[2] == "job-123"


# --- Session-to-file mapping (Redis SETs) ---

def test_register_file_for_session_adds_to_set(fake_redis):
    """register_file_for_session should call redis.sadd."""
    from app.core.queue import register_file_for_session
    register_file_for_session("session-123", "video.mp4")
    fake_redis.sadd.assert_called_once()


def test_get_files_for_session_returns_registered_files(fake_redis):
    """get_files_for_session should return files from redis.smembers."""
    fake_redis.smembers.return_value = {b"video.mp4", b"audio.webm"}
    from app.core.queue import get_files_for_session
    result = get_files_for_session("session-123")
    assert result == ["audio.webm", "video.mp4"]  # sorted


def test_get_files_for_session_returns_empty_for_unknown_session(fake_redis):
    """get_files_for_session should return empty list for unknown session."""
    fake_redis.smembers.return_value = set()
    from app.core.queue import get_files_for_session
    result = get_files_for_session("unknown-session")
    assert result == []


def test_clear_file_for_session_removes_one_file(fake_redis):
    """clear_file_for_session should call redis.srem."""
    from app.core.queue import clear_file_for_session
    clear_file_for_session("session-123", "video.mp4")
    fake_redis.srem.assert_called_once()


def test_clear_all_files_for_session_removes_all(fake_redis):
    """clear_all_files_for_session should call redis.delete."""
    from app.core.queue import clear_all_files_for_session
    clear_all_files_for_session("session-123")
    fake_redis.delete.assert_called_once()


def test_file_belongs_to_session_returns_true(fake_redis):
    """file_belongs_to_session should return True when sismember returns 1."""
    fake_redis.sismember.return_value = 1
    from app.core.queue import file_belongs_to_session
    result = file_belongs_to_session("session-123", "video.mp4")
    assert result == 1  # truthy


def test_file_belongs_to_session_returns_false(fake_redis):
    """file_belongs_to_session should return False when sismember returns 0."""
    fake_redis.sismember.return_value = 0
    from app.core.queue import file_belongs_to_session
    result = file_belongs_to_session("session-123", "nonexistent.mp4")
    assert result == 0  # falsy