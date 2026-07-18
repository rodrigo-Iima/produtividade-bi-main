"""Single-run filesystem lock for the local phase 6 job."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path


DEFAULT_LOCK_PATH = Path(os.getenv("ETL_RUNTIME_DIR", ".runtime")) / "etl.lock"


class LocalRunLock:
    """Prevent overlapping local ETL executions.

    This lock is host-local and works for a single EC2 instance. If the ETL is
    later distributed across workers or instances, replace it with a
    scheduler-level concurrency policy or a distributed lock.
    """

    def __init__(self, path: Path = DEFAULT_LOCK_PATH):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._file.close()
            self._file = None
            raise RuntimeError(
                f"Já existe uma execução em andamento ({self.path})"
            ) from exc

        self._file.seek(0)
        self._file.truncate()
        self._file.write(
            f"pid={os.getpid()}\n"
            f"started_at={datetime.now(timezone.utc).isoformat()}\n"
        )
        self._file.flush()

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.flush()
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> "LocalRunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
