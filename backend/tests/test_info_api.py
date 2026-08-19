"""
Tests for app.api.info — POST /api/info endpoint.

Mocks extract_info so no network calls are made.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_info_success(fake_yt_info):
    """POST /api/info with valid URL should return video metadata."""
    with patch("app.api.info.extract_info", return_value=fake_yt_info):
        response = client.post("/api/info", json={"url": "https://example.com/video"})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Video"
    assert data["uploader"] == "Test Channel"
    assert data["duration"] == 120
    assert data["thumbnail"] == "https://example.com/thumb.jpg"
    assert len(data["formats"]) == 2


def test_get_info_invalid_url():
    """POST /api/info with invalid URL should return 422 validation error."""
    response = client.post("/api/info", json={"url": "not-a-url"})
    assert response.status_code == 422


def test_get_info_missing_url():
    """POST /api/info without url field should return 422."""
    response = client.post("/api/info", json={})
    assert response.status_code == 422


def test_get_info_extractor_error():
    """POST /api/info when yt-dlp raises should return 400."""
    with patch("app.api.info.extract_info", side_effect=Exception("Video not found")):
        response = client.post("/api/info", json={"url": "https://example.com/bad"})

    assert response.status_code == 400
    assert "Video not found" in response.json()["detail"]