"""Update endpoint — self-update yt-dlp to the latest version on PyPI.

Useful when YouTube changes their anti-bot measures and downloads start
failing with 403 Forbidden. Calling this endpoint runs
`pip install --upgrade yt-dlp` inside the container, so the fix takes
effect immediately without rebuilding the Docker image.

Requires an API key (X-API-Key header) when UPDATE_API_KEY is set in the
environment. This prevents unauthorized users from triggering pip installs.
"""

from fastapi import APIRouter, HTTPException, Header

from app.core.yt_dlp_service import update_yt_dlp, get_version
from app.core.config import UPDATE_API_KEY

router = APIRouter()


@router.get("/update")
def check_version():
    """Return the currently installed yt-dlp version."""
    return {"version": get_version()}


@router.post("/update")
def trigger_update(x_api_key: str | None = Header(None)):
    """Upgrade yt-dlp to the latest version on PyPI.

    Requires X-API-Key header when UPDATE_API_KEY is configured.
    """
    if UPDATE_API_KEY and x_api_key != UPDATE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

    try:
        result = update_yt_dlp()
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))