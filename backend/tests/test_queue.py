"""
Tests for app.core.queue — Redis connection, Queue helpers,
session-scoped dedup helpers, and session-to-file mapping helpers.

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


# --- Session-scoped dedup (URL+quality per session) ---

def test_get_active_job_for_session_returns_none_when_empty(fake_redis):
    """get_active_job_for_session should return None when no mapping exists."""
    fake_redis.hget.return_value = None
    from app.core.queue import get_active_job_for_session
    result = get_active_job_for_session("session-123", "https://example.com/video", "1080p")
    assert result is None
    fake_redis.hget.assert_called_once()


def test_set_then_get_active_job_for_session(fake_redis):
    """set_active_job_for_session then get_active_job_for_session should return the job_id."""
    fake_redis.hget.return_value = b"job-123"

    from app.core.queue import set_active_job_for_session, get_active_job_for_session

    set_active_job_for_session("session-123", "https://example.com/video", "1080p", "job-123")
    result = get_active_job_for_session("session-123", "https://example.com/video", "1080p")

    assert result == "job-123"
    fake_redis.hset.assert_called_once()
    fake_redis.hget.assert_called_once()


def test_clear_active_job_for_session(fake_redis):
    """clear_active_job_for_session should call redis.hdel."""
    from app.core.queue import clear_active_job_for_session
    clear_active_job_for_session("session-123", "https://example.com/video", "1080p")
    fake_redis.hdel.assert_called_once()


def test_clear_all_dedup_for_session(fake_redis):
    """clear_all_dedup_for_session should call redis.delete with the dedup key."""
    from app.core.queue import clear_all_dedup_for_session
    clear_all_dedup_for_session("session-123")
    fake_redis.delete.assert_called_once()


def test_dedup_different_quality_different_fields(fake_redis):
    """Same URL with different quality should use different HGET fields."""
    from app.core.queue import set_active_job_for_session, _dedup_field

    set_active_job_for_session("session-123", "https://example.com/video", "1080p", "job-1")
    set_active_job_for_session("session-123", "https://example.com/video", "720p", "job-2")

    # Two hset calls, each with different field names
    assert fake_redis.hset.call_count == 2
    field1 = fake_redis.hset.call_args_list[0][0][1]
    field2 = fake_redis.hset.call_args_list[1][0][1]
    assert field1 != field2
    assert "1080p" in field1
    assert "720p" in field2


def test_dedup_different_session_different_keys(fake_redis):
    """Same URL+quality, different session should use different Redis keys."""
    from app.core.queue import set_active_job_for_session

    set_active_job_for_session("session-1", "https://example.com/video", "1080p", "job-1")
    set_active_job_for_session("session-2", "https://example.com/video", "1080p", "job-2")

    # Two hset calls, each with different key names
    assert fake_redis.hset.call_count == 2
    key1 = fake_redis.hset.call_args_list[0][0][0]
    key2 = fake_redis.hset.call_args_list[1][0][0]
    assert key1 != key2
    assert "session-1" in key1
    assert "session-2" in key2


def test_get_active_job_for_session_decodes_bytes(fake_redis):
    """get_active_job_for_session should decode bytes result to str."""
    fake_redis.hget.return_value = b"job-456"
    from app.core.queue import get_active_job_for_session
    result = get_active_job_for_session("session-123", "https://example.com/video", "1080p")
    assert result == "job-456"
    assert isinstance(result, str)


def test_get_active_job_for_session_handles_string(fake_redis):
    """get_active_job_for_session should handle string result (already decoded)."""
    fake_redis.hget.return_value = "job-789"
    from app.core.queue import get_active_job_for_session
    result = get_active_job_for_session("session-123", "https://example.com/video", "1080p")
    assert result == "job-789"


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


# --- Session-to-jobs mapping (Redis hash: job_id -> url) ---

def test_register_job_for_session_adds_to_hash(fake_redis):
    """register_job_for_session should call redis.hset."""
    from app.core.queue import register_job_for_session
    register_job_for_session("session-123", "job-1", "https://example.com/video")
    fake_redis.hset.assert_called_once()
    args = fake_redis.hset.call_args[0]
    assert "session-123" in args[0]  # key contains session_id
    assert args[1] == "job-1"  # field is job_id
    assert args[2] == "https://example.com/video"  # value is url


def test_get_jobs_for_session_returns_registered_jobs(fake_redis):
    """get_jobs_for_session should return list of {job_id, url}."""
    fake_redis.hgetall.return_value = {
        b"job-1": b"https://example.com/video1",
        b"job-2": b"https://example.com/video2",
    }
    from app.core.queue import get_jobs_for_session
    result = get_jobs_for_session("session-123")
    assert len(result) == 2
    job_ids = [j["job_id"] for j in result]
    assert "job-1" in job_ids
    assert "job-2" in job_ids
    for j in result:
        assert j["url"].startswith("https://example.com/")


def test_get_jobs_for_session_returns_empty_for_unknown_session(fake_redis):
    """get_jobs_for_session should return empty list for unknown session."""
    fake_redis.hgetall.return_value = {}
    from app.core.queue import get_jobs_for_session
    result = get_jobs_for_session("unknown-session")
    assert result == []


def test_clear_job_for_session_removes_one_job(fake_redis):
    """clear_job_for_session should call redis.hdel."""
    from app.core.queue import clear_job_for_session
    clear_job_for_session("session-123", "job-1")
    fake_redis.hdel.assert_called_once()
    args = fake_redis.hdel.call_args[0]
    assert "session-123" in args[0]
    assert args[1] == "job-1"


def test_clear_all_jobs_for_session_removes_all(fake_redis):
    """clear_all_jobs_for_session should call redis.delete."""
    from app.core.queue import clear_all_jobs_for_session
    clear_all_jobs_for_session("session-123")
    fake_redis.delete.assert_called_once()
    key = fake_redis.delete.call_args[0][0]
    assert "session-123" in key


def test_get_jobs_for_session_decodes_bytes(fake_redis):
    """get_jobs_for_session should decode bytes keys and values."""
    fake_redis.hgetall.return_value = {b"job-abc": b"https://example.com/v"}
    from app.core.queue import get_jobs_for_session
    result = get_jobs_for_session("session-123")
    assert result[0]["job_id"] == "job-abc"
    assert isinstance(result[0]["job_id"], str)
    assert result[0]["url"] == "https://example.com/v"
    assert isinstance(result[0]["url"], str)


# --- Serving flag (protects files from purge while being downloaded) ---

def test_set_serving_flag_sets_key_with_ttl(fake_redis):
    """set_serving_flag should call setex with correct key and TTL."""
    from app.core.queue import set_serving_flag
    set_serving_flag("session-123", "video.mp4")
    fake_redis.setex.assert_called_once()
    args = fake_redis.setex.call_args[0]
    assert "session-123" in args[0]
    assert "video.mp4" in args[0]
    assert args[1] == 3600  # SERVING_FLAG_TTL_SECONDS
    assert args[2] == "1"


def test_clear_serving_flag_deletes_key(fake_redis):
    """clear_serving_flag should call redis.delete."""
    from app.core.queue import clear_serving_flag
    clear_serving_flag("session-123", "video.mp4")
    fake_redis.delete.assert_called_once()
    key = fake_redis.delete.call_args[0][0]
    assert "session-123" in key
    assert "video.mp4" in key


def test_is_file_being_served_returns_true(fake_redis):
    """is_file_being_served should return True when flag exists."""
    fake_redis.exists.return_value = 1
    from app.core.queue import is_file_being_served
    result = is_file_being_served("session-123", "video.mp4")
    assert result is True


def test_is_file_being_served_returns_false(fake_redis):
    """is_file_being_served should return False when flag doesn't exist."""
    fake_redis.exists.return_value = 0
    from app.core.queue import is_file_being_served
    result = is_file_being_served("session-123", "video.mp4")
    assert result is False