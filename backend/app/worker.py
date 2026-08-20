"""
RQ worker entry point.

Run as a separate container:
    python -m app.worker

This connects to Redis and listens on the downloads queue.
When a job arrives, it calls the yt_dlp_service functions.

A background purge thread is also started to automatically clean up
old unclaimed files every PURGE_INTERVAL_SECONDS.
"""

from rq import Worker, Queue

from app.core.queue import get_queue, get_redis
from app.core.config import QUEUE_NAME
from app.purger import start_purge_thread


def run_worker():
    """Start the RQ worker and background purge thread."""
    conn = get_redis()
    queue = get_queue()

    # Start background purge thread for automatic file cleanup
    start_purge_thread()

    worker = Worker([queue], connection=conn)
    print(f"[worker] Listening on queue '{QUEUE_NAME}'...")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    run_worker()