"""Tests for app.models.schemas — Pydantic model validation."""

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    DownloadRequest,
    DownloadResponse,
    InfoRequest,
    InfoResponse,
)


# --- InfoRequest ---

def test_info_request_accepts_valid_url():
    req = InfoRequest(url="https://example.com/video")
    assert str(req.url) == "https://example.com/video"


def test_info_request_rejects_non_url():
    with pytest.raises(ValidationError):
        InfoRequest(url="not-a-url")


def test_info_request_rejects_missing_url():
    with pytest.raises(ValidationError):
        InfoRequest()


# --- InfoResponse ---

def test_info_response_minimal():
    """InfoResponse should accept just a title (other fields optional)."""
    resp = InfoResponse(title="Test Video")
    assert resp.title == "Test Video"
    assert resp.uploader is None
    assert resp.duration is None
    assert resp.thumbnail is None
    assert resp.formats == []


def test_info_response_full():
    resp = InfoResponse(
        title="Test",
        uploader="Channel",
        duration=120,
        thumbnail="https://example.com/thumb.jpg",
        formats=[{"format_id": "137"}],
    )
    assert resp.uploader == "Channel"
    assert resp.duration == 120
    assert len(resp.formats) == 1


# --- DownloadRequest ---

def test_download_request_defaults():
    """DownloadRequest should set defaults for format and audio_only."""
    req = DownloadRequest(url="https://example.com/video")
    assert req.format == "bestvideo+bestaudio/best"
    assert req.audio_only is False
    assert req.output_template is None


def test_download_request_audio_only():
    req = DownloadRequest(url="https://example.com/video", audio_only=True)
    assert req.audio_only is True


def test_download_request_custom_format():
    req = DownloadRequest(url="https://example.com/video", format="137+140")
    assert req.format == "137+140"


def test_download_request_custom_output_template():
    req = DownloadRequest(
        url="https://example.com/video",
        output_template="%(uploader)s/%(title)s.%(ext)s",
    )
    assert req.output_template == "%(uploader)s/%(title)s.%(ext)s"


def test_download_request_rejects_non_url():
    with pytest.raises(ValidationError):
        DownloadRequest(url="not-a-url")


def test_download_request_rejects_missing_url():
    with pytest.raises(ValidationError):
        DownloadRequest()


# --- DownloadResponse ---

def test_download_response_fields():
    resp = DownloadResponse(
        job_id="abc123",
        status="queued",
        message="Download job enqueued.",
    )
    assert resp.job_id == "abc123"
    assert resp.status == "queued"
    assert "enqueued" in resp.message


def test_download_response_minimal():
    """DownloadResponse requires all 3 fields."""
    with pytest.raises(ValidationError):
        DownloadResponse(job_id="abc123")  # missing status + message