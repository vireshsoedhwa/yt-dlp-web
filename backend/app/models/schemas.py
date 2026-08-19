"""Pydantic models / schemas for request and response bodies."""

from pydantic import BaseModel, HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    format: str = "bestvideo+bestaudio/best"
    audio_only: bool = False
    output_template: str | None = None  # override default naming


class DownloadResponse(BaseModel):
    job_id: str
    status: str  # "queued", "downloading", "completed", "failed"
    message: str


class InfoRequest(BaseModel):
    url: HttpUrl


class InfoResponse(BaseModel):
    title: str
    uploader: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    formats: list[dict] = []