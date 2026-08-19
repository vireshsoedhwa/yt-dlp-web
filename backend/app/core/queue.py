"""RQ queue, Redis connection, session-scoped dedup, and session-to-file mapping helpers."""

import hashlib
from redis import Redis
from rq import Queue

from app.core.config import REDIS_URL, QUEUE_NAME

# Shared Redis connection — created once, reused across requests
_redis_conn: Redis | None = None


def get_redis() -> Redis:
    """Return a shared Redis connection (lazy singleton)."""
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = Redis.from_url(REDIS_URL)
    return _redis_conn


def get_queue() -> Queue:
    """Return the download queue."""
    return Queue(QUEUE_NAME, connection=get_redis())


# --- Session-scoped dedup (URL + quality per session) ---

def _dedup_key(session_id: str) -> str:
    """Return the Redis key for a session's dedup hash (url|quality -> job_id)."""
    return f"ytdlp:dedup:{session_id}"


def _dedup_field(url: str, quality: str) -> str:
    """Return the hash field name for a URL+quality combo."""
    return f"{url}|{quality}"


def get_active_job_for_session(session_id: str, url: str, quality: str) -> str | None:
    """Return the active job_id for a URL+quality in a session, or None."""
    result = get_redis().hget(_dedup_key(session_id), _dedup_field(url, quality))
    if result is not None:
        return result.decode() if isinstance(result, bytes) else result
    return None


def set_active_job_for_session(session_id: str, url: str, quality: str, job_id: str) -> None:
    """Store the URL+quality -> job_id mapping in the session's dedup hash."""
    get_redis().hset(_dedup_key(session_id), _dedup_field(url, quality), job_id)


def clear_active_job_for_session(session_id: str, url: str, quality: str) -> None:
    """Delete the URL+quality -> job_id mapping from the session's dedup hash."""
    get_redis().hdel(_dedup_key(session_id), _dedup_field(url, quality))


def clear_all_dedup_for_session(session_id: str) -> None:
    """Delete the entire dedup hash for a session."""
    get_redis().delete(_dedup_key(session_id))


# --- Session-to-file mapping (Redis SETs) ---

def _session_file_key(session_id: str) -> str:
    """Return the Redis key for a session's file set."""
    return f"ytdlp:session:{session_id}:files"


def register_file_for_session(session_id: str, filename: str) -> None:
    """Add a filename to the session's file set in Redis."""
    get_redis().sadd(_session_file_key(session_id), filename)


def get_files_for_session(session_id: str) -> list[str]:
    """Return the list of filenames registered to a session."""
    result = get_redis().smembers(_session_file_key(session_id))
    return sorted(
        f.decode() if isinstance(f, bytes) else f for f in result
    )


def clear_file_for_session(session_id: str, filename: str) -> None:
    """Remove a filename from the session's file set."""
    get_redis().srem(_session_file_key(session_id), filename)


def clear_all_files_for_session(session_id: str) -> None:
    """Delete the session's entire file set from Redis."""
    get_redis().delete(_session_file_key(session_id))


def file_belongs_to_session(session_id: str, filename: str) -> bool:
    """Check if a filename is registered to a session."""
    return get_redis().sismember(_session_file_key(session_id), filename)