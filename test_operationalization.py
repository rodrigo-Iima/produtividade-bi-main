"""Unit tests for the local phase 6 operational controls."""

from pathlib import Path
from tempfile import TemporaryDirectory

from operationalization.lock import LocalRunLock
from operationalization.migration import run_migrations
from operationalization.runner import _run_with_retries, run_local
from database.migrations.dashboard_views import _transaction_body


def test_local_lock_rejects_overlapping_execution():
    with TemporaryDirectory() as directory:
        lock_path = Path(directory) / "etl.lock"
        with LocalRunLock(lock_path):
            try:
                with LocalRunLock(lock_path):
                    raise AssertionError("segunda execução deveria ser bloqueada")
            except RuntimeError as error:
                assert "execução em andamento" in str(error)


def test_retry_repeats_failed_operation_without_sleep():
    calls = []

    def operation():
        calls.append(len(calls) + 1)
        return 1 if len(calls) == 1 else 0

    assert _run_with_retries(operation, retries=1, retry_delay=0) == 0
    assert calls == [1, 2]


def test_local_runner_can_skip_database_acceptance():
    assert run_local(
        retries=0,
        retry_delay=0,
        run_acceptance=False,
        etl_operation=lambda: 0,
    ) == 0


def test_migration_entrypoint_applies_and_disposes():
    events = []

    assert run_migrations(
        migration_operation=lambda: events.append("migrate"),
        dispose_operation=lambda: events.append("dispose"),
    ) == 0
    assert events == ["migrate", "dispose"]


def test_migration_entrypoint_reports_failure_and_disposes():
    events = []

    def fail():
        events.append("migrate")
        raise RuntimeError("migration failure")

    assert run_migrations(
        migration_operation=fail,
        dispose_operation=lambda: events.append("dispose"),
    ) == 1
    assert events == ["migrate", "dispose"]


def test_dashboard_sql_loader_removes_outer_transaction_control():
    body = _transaction_body("BEGIN;\nSELECT 1;\nCOMMIT;\n")
    assert body == "SELECT 1;"


if __name__ == "__main__":
    tests = [
        test_local_lock_rejects_overlapping_execution,
        test_retry_repeats_failed_operation_without_sleep,
        test_local_runner_can_skip_database_acceptance,
        test_migration_entrypoint_applies_and_disposes,
        test_migration_entrypoint_reports_failure_and_disposes,
        test_dashboard_sql_loader_removes_outer_transaction_control,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\nAll {len(tests)} Phase 6 tests passed.")
