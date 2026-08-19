"""Tests for app.main — FastAPI app, health endpoint, and router registration."""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    """GET / should return status ok and service name."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "yt-dlp" in data["service"]


def test_app_has_info_router():
    """App should include the info router — /api/info should resolve."""
    # Test by making a request to the endpoint (422 validation = route exists)
    response = client.post("/api/info", json={})
    assert response.status_code == 422  # Missing url -> validation error, but route exists


def test_app_has_download_router():
    """App should include the download router — /api/download should resolve."""
    # With session header requirement, missing header -> 400 (not 422)
    # But missing url -> 422 comes first from Pydantic validation
    response = client.post("/api/download", json={})
    assert response.status_code == 422  # Missing url -> validation error, but route exists


def test_app_has_download_status_route():
    """App should include GET /api/download/{job_id}."""
    from rq.exceptions import NoSuchJobError
    with patch("app.api.download.Job.fetch", side_effect=NoSuchJobError), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/download/test123")
    # 404 = route exists, job not found
    assert response.status_code == 404


def test_app_has_update_router():
    """App should include the update router — GET /api/update should resolve."""
    with patch("app.api.update.get_version", return_value="2026.07.04"):
        response = client.get("/api/update")
    assert response.status_code == 200
    assert "version" in response.json()


def test_app_has_files_router():
    """App should include the files router — GET /api/files should resolve."""
    # Without session header -> 400 (route exists)
    response = client.get("/api/files")
    assert response.status_code == 400  # Missing session header, but route exists


def test_app_has_purge_endpoints():
    """App should include POST /api/purge and GET /api/purge/preview."""
    # POST /api/purge without session header -> 400 (route exists)
    response = client.post("/api/purge")
    assert response.status_code == 400  # Missing session header, but route exists

    # GET /api/purge/preview without session header -> 400 (route exists)
    response = client.get("/api/purge/preview")
    assert response.status_code == 400  # Missing session header, but route exists