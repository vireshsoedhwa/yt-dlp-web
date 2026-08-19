"""RQ queue, Redis connection, dedup, and session-to-file mapping helpers."""

import hashlib
from redis import Redis
from rq import Queue

from app.core.config import REDIS_URL, QUEUE_NAME, DEDUP_TTL_SECONDS

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


# --- Dedup helpers (URL-to-job mapping) ---

def _url_hash(url: str) -> str:
    """Return a deterministic MD5 hex digest of the URL for use as a Redis key."""
    return hashlib.md5(url.encode()).hexdigest()


def _dedup_key(url: str) -> str:
    """Return the Redis key for the URL-to-job dedup mapping."""
    return f"ytdlp:active:{_url_hash(url)}"


def get_active_job_for_url(url: str) -> str | None:
    """Return the active job_id for a URL, or None if no mapping exists."""
    result = get_redis().get(_dedup_key(url))
    if result is not None:
        return result.decode() if isinstance(result, bytes) else result
    return None


def set_active_job_for_url(url: str, job_id: str) -> None:
    """Store the URL-to-job mapping in Redis with a TTL."""
    get_redis().setex(_dedup_key(url), DEDUP_TTL_SECONDS, job_id)


def clear_active_job_for_url(url: str) -> None:
    """Delete the URL-to-job mapping from Redis."""
    get_redis().delete(_dedup_key(url))


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
    """Remove a filename from the session's file set in Redis."""
    get_redis().srem(_session_file_key(session_id), filename)


def clear_all_files_for_session(session_id: str) -> None:
    """Delete the session's entire file set from Redis."""
    get_redis().delete(_session_file_key(session_id))


def file_belongs_to_session(session_id: str, filename: str) -> bool:
    """Check if a filename is registered to a session."""
    return get_redis().sismember(_session_file_key(session_id), filename)