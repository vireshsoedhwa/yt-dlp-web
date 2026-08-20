"""
Download endpoint — enqueue jobs via RQ with session-scoped dedup.

The API enqueues a download job and returns immediately with a job_id.
The RQ worker (separate container) picks up the job and runs the download.

Features:
- Session-scoped dedup: if an active job for the same URL+quality exists
  in the same session, return its job_id instead of creating a duplicate
- Session: X-Session-ID header associates files with the requesting browser
- Cleanup: polling a finished/failed job clears the dedup mapping
- Job restoration: GET /api/jobs returns all jobs for a session (for page refresh)
- Job dismissal: DELETE /api/jobs/{job_id} removes a job from the session
"""

from fastapi import APIRouter, HTTPException, Header
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.models.schemas import DownloadRequest, DownloadResponse
from app.core.queue import (
    get_queue,
    get_redis,
    get_active_job_for_session,
    set_active_job_for_session,
    clear_active_job_for_session,
    register_job_for_session,
    get_jobs_for_session,
    clear_job_for_session,
    check_rate_limit,
)
from app.core.config import RATE_LIMIT_DOWNLOADS, RATE_LIMIT_WINDOW_SECONDS
from app.core.files_service import _validate_session_id
from app.core.yt_dlp_service import download_video

router = APIRouter()


@router.post("/download", response_model=DownloadResponse)
def start_download(
    req: DownloadRequest,
    x_session_id: str | None = Header(None),
):
    """Enqueue a download job. Returns immediately with a job_id."""
    url = str(req.url)
    quality = req.quality

    # Session ID is required for file isolation
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    # Validate session ID format (prevent path traversal)
    try:
        _validate_session_id(x_session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    # Rate limit per session
    if not check_rate_limit(
        f"ytdlp:ratelimit:dl:{x_session_id}",
        RATE_LIMIT_DOWNLOADS,
        RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # Dedup check: is there already an active job for this URL+quality in this session?
    existing_job_id = get_active_job_for_session(x_session_id, url, quality)
    if existing_job_id:
        try:
            existing_job = Job.fetch(existing_job_id, connection=get_redis())
            status = existing_job.get_status()
            if status in ("queued", "started"):
                # Active job exists -- return it instead of creating a duplicate
                # Re-register in session jobs hash (in case it was cleared)
                register_job_for_session(x_session_id, existing_job_id, url)
                return DownloadResponse(
                    job_id=existing_job_id,
                    status="already_queued",
                    message="Download job already in progress.",
                )
            # Job is finished or failed -- clear mapping and proceed
            clear_active_job_for_session(x_session_id, url, quality)
        except NoSuchJobError:
            # Job was deleted from Redis -- clear mapping and proceed
            clear_active_job_for_session(x_session_id, url, quality)

    # Enqueue new job
    queue = get_queue()
    job = queue.enqueue(
        download_video,
        url=url,
        quality=quality,
        audio_only=req.audio_only,
        session_id=x_session_id,
        job_timeout=3600,  # 1 hour max per download
        result_ttl=86400,  # keep result for 24h
    )

    # Set dedup mapping
    set_active_job_for_session(x_session_id, url, quality, job.id)

    # Register job in session jobs hash (for restoration on page refresh)
    register_job_for_session(x_session_id, job.id, url)

    return DownloadResponse(
        job_id=job.id,
        status="queued",
        message="Download job enqueued.",
    )


@router.get("/download/{job_id}")
def get_job_status(job_id: str):
    """Check the status of a download job."""
    try:
        job = Job.fetch(job_id, connection=get_redis())
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job.get_status()  # queued, started, finished, failed

    # Clean up dedup mapping when job reaches terminal state
    if status in ("finished", "failed"):
        # Get URL and quality from job kwargs
        job_url = job.kwargs.get("url") if job.kwargs else None
        job_quality = job.kwargs.get("quality") if job.kwargs else None
        job_session = job.kwargs.get("session_id") if job.kwargs else None
        if job_url and job_quality and job_session:
            clear_active_job_for_session(job_session, job_url, job_quality)

    return {
        "job_id": job.id,
        "status": status,
        "result": job.result,
        "error": str(job.exc_info) if job.exc_info else None,
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }


@router.get("/jobs")
def list_jobs(x_session_id: str | None = Header(None)):
    """List all jobs for the current session with their status.
    Jobs that have been finished/failed longer than JOB_CARD_TTL_HOURS
    are filtered out so they don't reappear on page refresh."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    from datetime import datetime, timedelta, timezone
    from app.core.config import JOB_CARD_TTL_HOURS

    jobs = get_jobs_for_session(x_session_id)
    result = []
    for job_info in jobs:
        job_id = job_info["job_id"]
        try:
            job = Job.fetch(job_id, connection=get_redis())
            status = job.get_status()

            # Filter out expired job cards (finished/failed > JOB_CARD_TTL_HOURS ago)
            if status in ("finished", "failed") and job.ended_at:
                ended_utc = job.ended_at.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - ended_utc
                if age > timedelta(hours=JOB_CARD_TTL_HOURS):
                    # Card has expired — skip it
                    # Don't clear from session hash (purge will clean up the file at 3h)
                    continue

            result.append({
                "job_id": job_id,
                "url": job_info["url"],
                "status": status,
                "result": job.result,
                "error": str(job.exc_info) if job.exc_info else None,
                "ended_at": job.ended_at.isoformat() if job.ended_at else None,
            })
        except NoSuchJobError:
            # Job expired from Redis — clear from session and skip
            clear_job_for_session(x_session_id, job_id)

    return {"jobs": result}


@router.delete("/jobs/{job_id}")
def dismiss_job(
    job_id: str,
    x_session_id: str | None = Header(None),
):
    """Dismiss a job from the session's job list."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    clear_job_for_session(x_session_id, job_id)

    return {"deleted": job_id}