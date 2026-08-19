"""
Update endpoint — self-update yt-dlp to the latest version on PyPI.

Useful when YouTube changes their anti-bot measures and downloads start
failing with 403 Forbidden. Calling this endpoint runs
`pip install --upgrade yt-dlp` inside the container, so the fix takes
effect immediately without rebuilding the Docker image.
"""

from fastapi import APIRouter, HTTPException

from app.core.yt_dlp_service import update_yt_dlp, get_version

router = APIRouter()


@router.get("/update")
def check_version():
    """Return the currently installed yt-dlp version."""
    return {"version": get_version()}


@router.post("/update")
def trigger_update():
    """Upgrade yt-dlp to the latest version on PyPI."""
    try:
        result = update_yt_dlp()
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))