"""Info endpoint — extract video metadata without downloading."""

from fastapi import APIRouter, HTTPException, Header, Request

from app.models.schemas import InfoRequest, InfoResponse
from app.core.yt_dlp_service import extract_info
from app.core.queue import check_rate_limit
from app.core.config import RATE_LIMIT_INFO, RATE_LIMIT_WINDOW_SECONDS

router = APIRouter()


@router.post("/info", response_model=InfoResponse)
def get_info(
    req: InfoRequest,
    request: Request,
    x_session_id: str | None = Header(None),
):
    """Return metadata (title, uploader, duration, formats) for a URL."""
    # Rate limit by session ID (if available) or client IP
    rate_key = f"ytdlp:ratelimit:info:{x_session_id or (request.client.host if request.client else 'unknown')}"
    if not check_rate_limit(rate_key, RATE_LIMIT_INFO, RATE_LIMIT_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    try:
        return extract_info(str(req.url))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))