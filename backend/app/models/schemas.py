"""Pydantic models / schemas for request and response bodies."""

from pydantic import BaseModel, HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    quality: str = "1080p"  # "1080p", "720p", "480p", "360p", "audio"
    audio_only: bool = False


class DownloadResponse(BaseModel):
    job_id: str
    status: str  # "queued", "already_queued", "completed", "failed"
    message: str


class InfoRequest(BaseModel):
    url: HttpUrl


class InfoResponse(BaseModel):
    title: str
    uploader: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    formats: list[dict] = []