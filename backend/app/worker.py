"""
RQ worker entry point.

Run as a separate container:
    python -m app.worker

This connects to Redis and listens on the downloads queue.
When a job arrives, it calls the yt_dlp_service functions.
"""

from rq import Worker, Queue

from app.core.queue import get_queue, get_redis
from app.core.config import QUEUE_NAME


def run_worker():
    """Start the RQ worker. Blocks forever listening for jobs."""
    conn = get_redis()
    queue = get_queue()
    worker = Worker([queue], connection=conn)
    print(f"[worker] Listening on queue '{QUEUE_NAME}'...")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    run_worker()