"""
Tests for app.api.download — POST /api/download and GET /api/download/{job_id}.

Mocks RQ queue and Job so no Redis server is needed.
All POST /api/download tests include X-Session-ID header.
"""

from unittest.mock import patch, MagicMock
from datetime import datetime
import pytest
from rq.exceptions import NoSuchJobError
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SESSION_HEADERS = {"X-Session-ID": "test-session-123"}


@pytest.fixture(autouse=True)
def mock_rate_limit():
    """Auto-mock rate limiting so tests don't need Redis."""
    with patch("app.api.download.check_rate_limit", return_value=True):
        yield


# --- POST /api/download ---

def test_start_download_enqueues_job(fake_queue, fake_job):
    """POST /api/download should enqueue a job and return job_id + queued status."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session") as mock_set, \
         patch("app.api.download.register_job_for_session") as mock_register:
        response = client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "1080p",
            "audio_only": False,
        }, headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "abc12345"
    assert data["status"] == "queued"
    # Verify dedup mapping was set
    mock_set.assert_called_once()
    # Verify job was registered in session jobs hash
    mock_register.assert_called_once_with(
        "test-session-123", "abc12345", "https://example.com/video"
    )


def test_start_download_passes_quality_to_job(fake_queue, fake_job):
    """enqueue should be called with quality (not format) in kwargs."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session"):
        client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "720p",
            "audio_only": True,
        }, headers=SESSION_HEADERS)

    call_kwargs = fake_queue.enqueue.call_args[1]
    assert call_kwargs["url"] == "https://example.com/video"
    assert call_kwargs["quality"] == "720p"
    assert call_kwargs["audio_only"] is True
    assert call_kwargs["session_id"] == "test-session-123"


def test_start_download_uses_defaults_for_omitted_fields(fake_queue, fake_job):
    """Omitted fields should fall back to defaults (quality='1080p', audio_only=False)."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session"):
        client.post("/api/download", json={
            "url": "https://example.com/video",
        }, headers=SESSION_HEADERS)

    call_kwargs = fake_queue.enqueue.call_args[1]
    assert call_kwargs["quality"] == "1080p"
    assert call_kwargs["audio_only"] is False


def test_start_download_invalid_url():
    """POST /api/download with invalid URL should return 422."""
    response = client.post("/api/download", json={"url": "not-a-url"}, headers=SESSION_HEADERS)
    assert response.status_code == 422


def test_start_download_missing_url():
    """POST /api/download without url should return 422."""
    response = client.post("/api/download", json={}, headers=SESSION_HEADERS)
    assert response.status_code == 422


def test_start_download_sets_job_timeout(fake_queue, fake_job):
    """Job timeout should be 3600s (1 hour)."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session"):
        client.post("/api/download", json={"url": "https://example.com/video"}, headers=SESSION_HEADERS)

    call_kwargs = fake_queue.enqueue.call_args[1]
    assert call_kwargs["job_timeout"] == 3600


def test_start_download_sets_result_ttl(fake_queue, fake_job):
    """Result TTL should be 86400s (24h)."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session"):
        client.post("/api/download", json={"url": "https://example.com/video"}, headers=SESSION_HEADERS)

    call_kwargs = fake_queue.enqueue.call_args[1]
    assert call_kwargs["result_ttl"] == 86400


# --- POST /api/download -- session header validation ---

def test_start_download_returns_400_without_session_header(fake_queue, fake_job):
    """POST /api/download without X-Session-ID header should return 400."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue):
        response = client.post("/api/download", json={"url": "https://example.com/video"})
    assert response.status_code == 400


# --- POST /api/download -- dedup ---

def test_start_download_dedup_returns_existing_job(fake_queue, fake_job):
    """When dedup finds an active job (same url+quality), should return the existing job_id."""
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value="existing-job-id"), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        # Set status to "queued" so dedup returns the existing job
        fake_job.get_status.return_value = "queued"
        response = client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "1080p",
        }, headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "existing-job-id"
    assert data["status"] == "already_queued"


def test_start_download_dedup_different_quality_new_job(fake_queue, fake_job):
    """Same URL, different quality -> should create a new job (different dedup field)."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session") as mock_set, \
         patch("app.api.download.register_job_for_session"):
        response = client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "720p",
        }, headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    fake_queue.enqueue.assert_called_once()
    mock_set.assert_called_once_with("test-session-123", "https://example.com/video", "720p", "abc12345")


def test_start_download_creates_new_job_after_completion(fake_queue, fake_job):
    """When dedup finds a finished job, should create a new job."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value="old-job-id"), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session") as mock_clear, \
         patch("app.api.download.set_active_job_for_session") as mock_set, \
         patch("app.api.download.register_job_for_session"):
        fake_job.get_status.return_value = "finished"
        response = client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "1080p",
        }, headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    # Should have enqueued a new job
    fake_queue.enqueue.assert_called_once()
    # Should have cleared the old dedup mapping
    mock_clear.assert_called_once()
    # Should have set a new dedup mapping
    mock_set.assert_called_once()


def test_start_download_creates_new_job_after_failure(fake_queue, fake_job):
    """When dedup finds a failed job, should create a new job."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value="old-job-id"), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session") as mock_clear, \
         patch("app.api.download.set_active_job_for_session") as mock_set, \
         patch("app.api.download.register_job_for_session"):
        fake_job.get_status.return_value = "failed"
        response = client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "1080p",
        }, headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    fake_queue.enqueue.assert_called_once()
    mock_clear.assert_called_once()
    mock_set.assert_called_once()


def test_start_download_sets_dedup_mapping(fake_queue, fake_job):
    """After enqueueing, set_active_job_for_session should be called with session_id, url, quality."""
    fake_queue.enqueue.return_value = fake_job
    with patch("app.api.download.get_queue", return_value=fake_queue), \
         patch("app.api.download.get_active_job_for_session", return_value=None), \
         patch("app.api.download.set_active_job_for_session") as mock_set, \
         patch("app.api.download.register_job_for_session"):
        client.post("/api/download", json={
            "url": "https://example.com/video",
            "quality": "720p",
        }, headers=SESSION_HEADERS)

    mock_set.assert_called_once_with("test-session-123", "https://example.com/video", "720p", "abc12345")


# --- GET /api/download/{job_id} ---

def test_get_job_status_success(fake_job):
    """GET /api/download/{job_id} should return job status and metadata."""
    fake_job.get_status.return_value = "started"  # in-progress to avoid dedup cleanup
    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session"):
        response = client.get("/api/download/abc12345")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "abc12345"
    assert data["status"] == "started"
    assert data["result"]["status"] == "completed"
    assert data["error"] is None


def test_get_job_status_includes_timestamps(fake_job):
    """Response should include enqueued_at, started_at, ended_at."""
    fake_job.get_status.return_value = "started"  # in-progress to avoid dedup cleanup
    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session"):
        response = client.get("/api/download/abc12345")

    data = response.json()
    assert data["enqueued_at"] is not None
    assert data["started_at"] is not None
    assert data["ended_at"] is not None


def test_get_job_status_returns_404_for_unknown_job():
    """GET /api/download/{job_id} for non-existent job should return 404."""
    with patch("app.api.download.Job.fetch", side_effect=NoSuchJobError), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/download/nonexistent")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_job_status_failed_job():
    """GET /api/download/{job_id} for a failed job should include error info."""
    fake_job = MagicMock()
    fake_job.id = "failed123"
    fake_job.get_status.return_value = "failed"
    fake_job.kwargs = {
        "url": "https://example.com/video",
        "quality": "1080p",
        "session_id": "test-session-123",
    }
    fake_job.result = None
    fake_job.exc_info = "ValueError: Bad URL"
    fake_job.enqueued_at = datetime(2025, 1, 1, 12, 0, 0)
    fake_job.started_at = datetime(2025, 1, 1, 12, 0, 5)
    fake_job.ended_at = datetime(2025, 1, 1, 12, 0, 10)

    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session"):
        response = client.get("/api/download/failed123")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "ValueError" in data["error"]


# --- GET /api/download/{job_id} -- dedup cleanup ---

def test_get_job_status_clears_dedup_on_completion(fake_job):
    """Finished job should clear the dedup mapping with session_id, url, quality."""
    fake_job.get_status.return_value = "finished"
    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session") as mock_clear:
        response = client.get("/api/download/abc12345")

    assert response.status_code == 200
    mock_clear.assert_called_once_with("test-session-123", "https://example.com/video", "1080p")


def test_get_job_status_clears_dedup_on_failure():
    """Failed job should clear the dedup mapping with session_id, url, quality."""
    fake_job = MagicMock()
    fake_job.id = "failed123"
    fake_job.get_status.return_value = "failed"
    fake_job.kwargs = {
        "url": "https://example.com/badvideo",
        "quality": "720p",
        "session_id": "test-session-123",
    }
    fake_job.result = None
    fake_job.exc_info = "ValueError: Bad URL"
    fake_job.enqueued_at = datetime(2025, 1, 1, 12, 0, 0)
    fake_job.started_at = datetime(2025, 1, 1, 12, 0, 5)
    fake_job.ended_at = datetime(2025, 1, 1, 12, 0, 10)

    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session") as mock_clear:
        response = client.get("/api/download/failed123")

    assert response.status_code == 200
    mock_clear.assert_called_once_with("test-session-123", "https://example.com/badvideo", "720p")


def test_get_job_status_does_not_clear_dedup_while_in_progress():
    """Started (in-progress) job should NOT clear the dedup mapping."""
    fake_job = MagicMock()
    fake_job.id = "inprogress123"
    fake_job.get_status.return_value = "started"
    fake_job.kwargs = {
        "url": "https://example.com/video",
        "quality": "1080p",
        "session_id": "test-session-123",
    }
    fake_job.result = None
    fake_job.exc_info = None
    fake_job.enqueued_at = datetime(2025, 1, 1, 12, 0, 0)
    fake_job.started_at = datetime(2025, 1, 1, 12, 0, 5)
    fake_job.ended_at = None

    with patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()), \
         patch("app.api.download.clear_active_job_for_session") as mock_clear:
        response = client.get("/api/download/inprogress123")

    assert response.status_code == 200
    mock_clear.assert_not_called()


# --- GET /api/jobs ---

def test_list_jobs_returns_session_jobs(fake_job):
    """GET /api/jobs should return jobs for the session with status."""
    from datetime import datetime, timezone
    fake_job.get_status.return_value = "finished"
    # Set ended_at to recent so it's within the 2h card TTL
    fake_job.ended_at = datetime.now(timezone.utc)
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["job_id"] == "abc12345"
    assert data["jobs"][0]["url"] == "https://example.com/video"
    assert data["jobs"][0]["status"] == "finished"


def test_list_jobs_returns_400_without_session_header():
    """GET /api/jobs without X-Session-ID should return 400."""
    response = client.get("/api/jobs")
    assert response.status_code == 400


def test_list_jobs_returns_empty_for_session_with_no_jobs():
    """GET /api/jobs should return empty list for session with no jobs."""
    with patch("app.api.download.get_jobs_for_session", return_value=[]):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_list_jobs_clears_expired_jobs():
    """GET /api/jobs should clear jobs that no longer exist in Redis."""
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "expired-job", "url": "https://example.com/old"},
    ]), \
         patch("app.api.download.Job.fetch", side_effect=NoSuchJobError), \
         patch("app.api.download.clear_job_for_session") as mock_clear:
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"jobs": []}
    mock_clear.assert_called_once_with("test-session-123", "expired-job")


# --- DELETE /api/jobs/{job_id} ---

def test_dismiss_job_removes_from_session():
    """DELETE /api/jobs/{job_id} should clear the job from the session."""
    with patch("app.api.download.clear_job_for_session") as mock_clear:
        response = client.delete("/api/jobs/abc12345", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == "abc12345"
    mock_clear.assert_called_once_with("test-session-123", "abc12345")


def test_dismiss_job_returns_400_without_session_header():
    """DELETE /api/jobs/{job_id} without X-Session-ID should return 400."""
    response = client.delete("/api/jobs/abc12345")
    assert response.status_code == 400


# --- GET /api/jobs -- expired job filtering ---

def test_list_jobs_skips_expired_finished_jobs(fake_job):
    """GET /api/jobs should not return finished jobs older than JOB_CARD_TTL_HOURS."""
    from datetime import datetime, timedelta, timezone
    fake_job.get_status.return_value = "finished"
    # Set ended_at to 3 hours ago (expired, > 2h TTL)
    fake_job.ended_at = datetime.now(timezone.utc) - timedelta(hours=3)
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_list_jobs_returns_recent_finished_jobs(fake_job):
    """GET /api/jobs should return finished jobs younger than JOB_CARD_TTL_HOURS."""
    from datetime import datetime, timedelta, timezone
    fake_job.get_status.return_value = "finished"
    # Set ended_at to 30 minutes ago (within 2h TTL)
    fake_job.ended_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["job_id"] == "abc12345"


def test_list_jobs_skips_expired_failed_jobs(fake_job):
    """GET /api/jobs should not return failed jobs older than JOB_CARD_TTL_HOURS."""
    from datetime import datetime, timedelta, timezone
    fake_job.get_status.return_value = "failed"
    fake_job.ended_at = datetime.now(timezone.utc) - timedelta(hours=3)
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_list_jobs_includes_in_progress_jobs(fake_job):
    """GET /api/jobs should always include in-progress jobs (no ended_at)."""
    fake_job.get_status.return_value = "started"
    fake_job.ended_at = None
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "started"


# --- GET /api/jobs -- ended_at in response ---

def test_list_jobs_includes_ended_at(fake_job):
    """GET /api/jobs response should include ended_at when job has it."""
    from datetime import datetime, timezone
    fake_job.get_status.return_value = "finished"
    fake_job.ended_at = datetime.now(timezone.utc)
    with patch("app.api.download.get_jobs_for_session", return_value=[
        {"job_id": "abc12345", "url": "https://example.com/video"},
    ]), \
         patch("app.api.download.Job.fetch", return_value=fake_job), \
         patch("app.api.download.get_redis", return_value=MagicMock()):
        response = client.get("/api/jobs", headers=SESSION_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["jobs"][0]["ended_at"] is not None