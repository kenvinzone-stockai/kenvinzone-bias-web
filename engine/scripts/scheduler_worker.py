"""Dedicated scheduler process for the desktop deployment.

Streamlit owns UI sessions and reruns; it must not own durable background jobs.
An OS file lock ensures only one scheduler worker runs per workspace.
"""
from __future__ import annotations

import atexit
import logging
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings
from core.database import init_db
from ingestion.scheduler import PipelineScheduler

logger = logging.getLogger(__name__)


def _acquire_process_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    lock = _acquire_process_lock(settings.data_dir / "scheduler.worker.lock")
    if lock is None:
        logger.info("Scheduler worker already running; exiting duplicate process")
        return 0

    init_db()
    scheduler = PipelineScheduler.get()
    stop_event = threading.Event()

    def stop(*_args):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    atexit.register(lock.close)
    scheduler.start()
    # IntervalTrigger starts counting from process startup. Check once now so
    # frequent desktop restarts cannot postpone an already-due model forever.
    scheduler.run_predictive_bias()
    logger.info("Dedicated scheduler worker started")
    try:
        while not stop_event.wait(30):
            pass
    finally:
        scheduler.shutdown()
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
