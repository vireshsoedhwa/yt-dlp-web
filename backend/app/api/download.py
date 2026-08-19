"""
Download endpoint — enqueue jobs via RQ with dedup and session support.

The API enqueues a download job and returns immediately with a job_id.
The RQ worker (separate container) picks up the job and runs the download.

Features:
- Dedup: if an active job for the same URL exists, return its job_id
- Session: X-Session-ID header associates files with the requesting browser
- Cleanup: polling a finished/failed job clears the dedup mapping
"""

from fastapi import APIRouter, HTTPException, Header
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.models.schemas import DownloadRequest, DownloadResponse
from app.core.queue import (
    get_queue,
    get_redis,
    get_active_job_for_url,
    set_active_job_for_url,
    clear_active_job_for_url,
)
from app.core.yt_dlp_service import download_video

router = APIRouter()


@router.post("/download", response_model=DownloadResponse)
def start_download(
    req: DownloadRequest,
    x_session_id: str | None = Header(None),
):
    """Enqueue a download job. Returns immediately with a job_id."""
    url = str(req.url)

    # Session ID is required for file isolation
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    # Dedup check: is there already an active job for this URL?
    existing_job_id = get_active_job_for_url(url)
    if existing_job_id:
        try:
            existing_job = Job.fetch(existing_job_id, connection=get_redis())
            status = existing_job.get_status()
            if status in ("queued", "started"):
                # Active job exists -- return it instead of creating a duplicate
                return DownloadResponse(
                    job_id=existing_job_id,
                    status="already_queued",
                    message="Download job already in progress.",
                )
            # Job is finished or failed -- clear mapping and proceed
            clear_active_job_for_url(url)
        except NoSuchJobError:
            # Job was deleted from Redis -- clear mapping and proceed
            clear_active_job_for_url(url)

    # Enqueue new job
    queue = get_queue()
    job = queue.enqueue(
        download_video,
        url=url,
        format_str=req.format,
        audio_only=req.audio_only,
        output_template=req.output_template,
        session_id=x_session_id,
        job_timeout=3600,  # 1 hour max per download
        result_ttl=86400,  # keep result for 24h
    )

    # Set dedup mapping
    set_active_job_for_url(url, job.id)

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
        # Get URL from job kwargs
        job_url = job.kwargs.get("url") if job.kwargs else None
        if job_url:
            clear_active_job_for_url(job_url)

    return {
        "job_id": job.id,
        "status": status,
        "result": job.result,
        "error": str(job.exc_info) if job.exc_info else None,
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }