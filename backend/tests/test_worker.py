"""Tests for app.worker — RQ worker entry point."""

from unittest.mock import patch, MagicMock


def test_run_worker_creates_worker_and_calls_work():
    """run_worker should create a Worker and call worker.work()."""
    fake_worker = MagicMock()
    with patch("app.worker.Worker", return_value=fake_worker) as mock_worker_cls, \
         patch("app.worker.get_queue", return_value=MagicMock()), \
         patch("app.worker.get_redis", return_value=MagicMock()):
        from app.worker import run_worker
        run_worker()

    mock_worker_cls.assert_called_once()
    fake_worker.work.assert_called_once()
    # Should enable scheduler
    assert fake_worker.work.call_args[1]["with_scheduler"] is True


def test_run_worker_listens_on_downloads_queue():
    """Worker should be initialized with the 'downloads' queue."""
    fake_queue = MagicMock()
    with patch("app.worker.Worker") as mock_worker_cls, \
         patch("app.worker.get_queue", return_value=fake_queue), \
         patch("app.worker.get_redis", return_value=MagicMock()):
        from app.worker import run_worker
        run_worker()

    # Worker receives [queue] as first positional arg
    call_args = mock_worker_cls.call_args[0]
    assert fake_queue in call_args[0]


def test_run_worker_uses_redis_connection():
    """Worker should be initialized with a Redis connection."""
    fake_conn = MagicMock()
    with patch("app.worker.Worker") as mock_worker_cls, \
         patch("app.worker.get_queue", return_value=MagicMock()), \
         patch("app.worker.get_redis", return_value=fake_conn):
        from app.worker import run_worker
        run_worker()

    call_kwargs = mock_worker_cls.call_args[1]
    assert call_kwargs["connection"] is fake_conn