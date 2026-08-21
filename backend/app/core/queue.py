"""RQ queue, Redis connection, session-scoped dedup, and session-to-file mapping helpers."""

import hashlib
from redis import Redis
from rq import Queue

from app.core.config import REDIS_URL, QUEUE_NAME, SERVING_FLAG_TTL_SECONDS

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


# --- Session-to-jobs mapping (Redis hash: job_id -> url) ---

def _session_jobs_key(session_id: str) -> str:
    """Return the Redis key for a session's jobs hash."""
    return f"ytdlp:session:{session_id}:jobs"


def register_job_for_session(session_id: str, job_id: str, url: str) -> None:
    """Store a job_id -> url mapping in the session's jobs hash."""
    get_redis().hset(_session_jobs_key(session_id), job_id, url)


def get_jobs_for_session(session_id: str) -> list[dict]:
    """Return list of {job_id, url} for all jobs in the session."""
    raw = get_redis().hgetall(_session_jobs_key(session_id))
    return [
        {
            "job_id": k.decode() if isinstance(k, bytes) else k,
            "url": v.decode() if isinstance(v, bytes) else v,
        }
        for k, v in raw.items()
    ]


def clear_job_for_session(session_id: str, job_id: str) -> None:
    """Remove a job_id from the session's jobs hash."""
    get_redis().hdel(_session_jobs_key(session_id), job_id)


def clear_all_jobs_for_session(session_id: str) -> None:
    """Delete the session's entire jobs hash."""
    get_redis().delete(_session_jobs_key(session_id))


# --- Serving flag (protects files from purge while being downloaded) ---

def _serving_flag_key(session_id: str, filename: str) -> str:
    """Return the Redis key for a file's serving flag."""
    return f"ytdlp:serving:{session_id}:{filename}"


def set_serving_flag(session_id: str, filename: str) -> None:
    """Set a flag indicating the file is being actively downloaded.
    The purger checks this and skips files with an active flag.
    Auto-expires after SERVING_FLAG_TTL_SECONDS (default: 1 hour)."""
    get_redis().setex(_serving_flag_key(session_id, filename), SERVING_FLAG_TTL_SECONDS, "1")


def clear_serving_flag(session_id: str, filename: str) -> None:
    """Clear the serving flag after the download completes."""
    get_redis().delete(_serving_flag_key(session_id, filename))


def is_file_being_served(session_id: str, filename: str) -> bool:
    """Check if a file is currently being downloaded (serving flag is set)."""
    return get_redis().exists(_serving_flag_key(session_id, filename)) > 0


# --- Job progress (real-time download progress from yt-dlp) ---

def _progress_key(job_id: str) -> str:
    """Return the Redis key for a job's progress data."""
    return f"ytdlp:progress:{job_id}"


def set_job_progress(job_id: str, percentage: str, speed: str, eta: str,
                     downloaded_bytes: int, total_bytes: int) -> None:
    """Store download progress for a job in Redis with a 300s TTL."""
    redis = get_redis()
    key = _progress_key(job_id)
    redis.hset(key, mapping={
        "percentage": percentage,
        "speed": speed,
        "eta": eta,
        "downloaded_bytes": str(downloaded_bytes),
        "total_bytes": str(total_bytes),
    })
    redis.expire(key, 300)


def get_job_progress(job_id: str) -> dict | None:
    """Return progress data for a job, or None if no progress is stored."""
    raw = get_redis().hgetall(_progress_key(job_id))
    if not raw:
        return None
    return {
        "percentage": raw.get(b"percentage", b"").decode() if isinstance(raw.get(b"percentage"), bytes) else raw.get("percentage", ""),
        "speed": raw.get(b"speed", b"").decode() if isinstance(raw.get(b"speed"), bytes) else raw.get("speed", ""),
        "eta": raw.get(b"eta", b"").decode() if isinstance(raw.get(b"eta"), bytes) else raw.get("eta", ""),
        "downloaded_bytes": int(raw.get(b"downloaded_bytes", b"0") or b"0"),
        "total_bytes": int(raw.get(b"total_bytes", b"0") or b"0"),
    }


def clear_job_progress(job_id: str) -> None:
    """Delete progress data for a job."""
    get_redis().delete(_progress_key(job_id))


# --- Rate limiting ---

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Check if a request is within the rate limit.
    Uses Redis INCR with a sliding window.
    Returns True if allowed, False if rate limited."""
    redis = get_redis()
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window_seconds)
    return count <= max_requests