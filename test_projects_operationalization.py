from __future__ import annotations

from datetime import datetime, timezone

import operationalization.projects as project_ops


class _NoopLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


class _Logger:
    def __init__(self, run_id):
        self.events = []

    def start(self, step):
        self.events.append(("start", step))

    def finish(self, step, result=None):
        self.events.append(("finish", step, result))

    def fail(self, step, error):
        self.events.append(("fail", step, str(error)))


class _Hierarchy:
    calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "epics_extracted": 1,
            "children_extracted": 2,
            "subtasks_extracted": 1,
            "issues_loaded": 4,
            "relations_loaded": 3,
        }


def test_incremental_project_pipeline_uses_watermark_and_does_not_need_flow(
    monkeypatch,
):
    watermark = datetime(2026, 8, 18, 10, tzinfo=timezone.utc)
    state_updates = []
    changelog_calls = []
    _Hierarchy.calls = []

    monkeypatch.setattr(project_ops, "EtlRunLogger", _Logger)
    monkeypatch.setattr(project_ops, "_get_watermark", lambda: watermark)
    monkeypatch.setattr(
        project_ops,
        "_set_source_state",
        lambda **kwargs: state_updates.append(kwargs),
    )
    monkeypatch.setattr(
        project_ops,
        "_get_last_project_record_at",
        lambda projects: None,
    )
    monkeypatch.setattr(project_ops, "validate_project_data", lambda: {
        "status": "passed",
        "checks": {"portfolio_rows": 1},
    })
    monkeypatch.setattr(project_ops, "reconcile_project_data", lambda: {
        "status": "reconciled",
        "checks": {"portfolio_rows": 1},
    })

    def changelog(**kwargs):
        changelog_calls.append(kwargs)
        return 2

    report = project_ops.run_project_pipeline(
        full=False,
        resume=True,
        lock_factory=_NoopLock,
        hierarchy_factory=_Hierarchy,
        changelog_operation=changelog,
    )

    assert report["status"] == "success"
    assert _Hierarchy.calls[0]["updated_since"] == watermark
    assert _Hierarchy.calls[0]["reconcile_absence"] is False
    assert changelog_calls[0]["incremental"] is True
    assert changelog_calls[0]["resume"] is True
    assert state_updates[0]["status"] == "running"
    assert state_updates[-1]["status"] == "success"


def test_project_pipeline_failure_can_be_retried_after_interruption(monkeypatch):
    state_updates = []
    attempts = []
    _Hierarchy.calls = []

    monkeypatch.setattr(project_ops, "EtlRunLogger", _Logger)
    monkeypatch.setattr(project_ops, "_get_watermark", lambda: None)
    monkeypatch.setattr(
        project_ops,
        "_set_source_state",
        lambda **kwargs: state_updates.append(kwargs),
    )
    monkeypatch.setattr(
        project_ops,
        "_get_last_project_record_at",
        lambda projects: None,
    )
    monkeypatch.setattr(
        project_ops,
        "validate_project_data",
        lambda: {"status": "passed", "checks": {"portfolio_rows": 1}},
    )
    monkeypatch.setattr(
        project_ops,
        "reconcile_project_data",
        lambda: {"status": "reconciled", "checks": {"portfolio_rows": 1}},
    )

    def changelog(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("interrupção simulada")
        return 0

    first = project_ops.run_project_pipeline(
        full=False,
        resume=True,
        lock_factory=_NoopLock,
        hierarchy_factory=_Hierarchy,
        changelog_operation=changelog,
    )
    second = project_ops.run_project_pipeline(
        full=False,
        resume=True,
        lock_factory=_NoopLock,
        hierarchy_factory=_Hierarchy,
        changelog_operation=changelog,
    )

    assert first["status"] == "failed"
    assert second["status"] == "success"
    assert state_updates[-1]["status"] == "success"
    assert len(attempts) == 2
