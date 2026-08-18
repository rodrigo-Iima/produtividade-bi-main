"""Single-run filesystem lock for the local phase 6 job."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path

from sqlalchemy import text


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


class PostgresAdvisoryLock:
    """Session-level PostgreSQL lock shared by all project job runners."""

    def __init__(self, name: str = "produtividade.project_pipeline", engine_ref=None):
        self.name = name
        self._engine = engine_ref
        self._connection = None

    def acquire(self) -> None:
        if self._engine is None:
            from database.connection import engine

            self._engine = engine
        self._connection = self._engine.connect()
        acquired = self._connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:lock_name))"),
            {"lock_name": self.name},
        ).scalar()
        if not acquired:
            self._connection.close()
            self._connection = None
            raise RuntimeError(
                f"Já existe uma execução de projetos em andamento ({self.name})"
            )

    def release(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_name))"),
                {"lock_name": self.name},
            )
        finally:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "PostgresAdvisoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
