"""
Tests for app.api.update — GET /api/update (version check) and POST /api/update (self-upgrade).

Mocks yt_dlp_service functions so no pip/network calls are made.
"""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# --- GET /api/update ---

def test_get_version_returns_200():
    """GET /api/update should return 200 with the current yt-dlp version."""
    with patch("app.api.update.get_version", return_value="2026.07.04"):
        response = client.get("/api/update")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "2026.07.04"


def test_get_version_returns_string():
    """GET /api/update should return version as a string."""
    with patch("app.api.update.get_version", return_value="2026.06.09"):
        response = client.get("/api/update")

    assert response.status_code == 200
    assert isinstance(response.json()["version"], str)


# --- POST /api/update ---

def test_post_update_success():
    """POST /api/update should return 200 with success result on successful upgrade."""
    fake_result = {
        "status": "success",
        "old_version": "2026.06.09",
        "new_version": "2026.07.04",
        "stdout": "Successfully installed yt-dlp-2026.07.04",
    }
    with patch("app.api.update.update_yt_dlp", return_value=fake_result):
        response = client.post("/api/update")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["old_version"] == "2026.06.09"
    assert data["new_version"] == "2026.07.04"


def test_post_update_pip_failure_returns_500():
    """POST /api/update should return 500 when pip upgrade fails."""
    fake_result = {
        "status": "failed",
        "old_version": "2026.06.09",
        "error": "ERROR: Could not install yt-dlp",
        "returncode": 1,
    }
    with patch("app.api.update.update_yt_dlp", return_value=fake_result):
        response = client.post("/api/update")

    assert response.status_code == 500
    data = response.json()
    assert "failed" in str(data["detail"])


def test_post_update_unexpected_exception_returns_500():
    """POST /api/update should return 500 on unexpected exceptions."""
    with patch("app.api.update.update_yt_dlp", side_effect=RuntimeError("Unexpected")):
        response = client.post("/api/update")

    assert response.status_code == 500
    assert "Unexpected" in response.json()["detail"]


# --- POST /api/update -- API key auth ---

def test_post_update_with_correct_api_key():
    """POST /api/update with correct API key should return 200."""
    fake_result = {
        "status": "success",
        "old_version": "2026.06.09",
        "new_version": "2026.07.04",
        "stdout": "Successfully installed yt-dlp-2026.07.04",
    }
    with patch("app.api.update.UPDATE_API_KEY", "secret-key"), \
         patch("app.api.update.update_yt_dlp", return_value=fake_result):
        response = client.post("/api/update", headers={"X-API-Key": "secret-key"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_post_update_with_wrong_api_key():
    """POST /api/update with wrong API key should return 403."""
    with patch("app.api.update.UPDATE_API_KEY", "secret-key"):
        response = client.post("/api/update", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 403


def test_post_update_without_api_key_when_required():
    """POST /api/update without API key should return 403 when UPDATE_API_KEY is set."""
    with patch("app.api.update.UPDATE_API_KEY", "secret-key"):
        response = client.post("/api/update")

    assert response.status_code == 403


def test_post_update_no_auth_when_key_unset():
    """POST /api/update should work without API key when UPDATE_API_KEY is empty."""
    fake_result = {
        "status": "success",
        "old_version": "2026.06.09",
        "new_version": "2026.07.04",
        "stdout": "Successfully installed yt-dlp-2026.07.04",
    }
    with patch("app.api.update.UPDATE_API_KEY", ""), \
         patch("app.api.update.update_yt_dlp", return_value=fake_result):
        response = client.post("/api/update")

    assert response.status_code == 200