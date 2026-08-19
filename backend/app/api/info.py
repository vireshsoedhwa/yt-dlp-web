"""Info endpoint — extract video metadata without downloading."""

from fastapi import APIRouter, HTTPException

from app.models.schemas import InfoRequest, InfoResponse
from app.core.yt_dlp_service import extract_info

router = APIRouter()


@router.post("/info", response_model=InfoResponse)
def get_info(req: InfoRequest):
    """Return metadata (title, uploader, duration, formats) for a URL."""
    try:
        return extract_info(str(req.url))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))