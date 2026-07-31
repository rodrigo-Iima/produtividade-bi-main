"""Tests for Flow orchestration inside the main ETL pipeline."""

import main


def test_flow_steps_can_be_disabled(monkeypatch, capsys):
    monkeypatch.setattr(main, "FLOW_ENABLED", False)

    assert main._run_flow_steps(None) == []
    assert "FLOW_ENABLED=false" in capsys.readouterr().out


def test_flow_steps_run_identity_before_points(monkeypatch):
    events = []
    monkeypatch.setattr(main, "FLOW_ENABLED", True)
    monkeypatch.setattr(
        main,
        "FlowIdentityETL",
        lambda: _FakeIdentityETL(events),
    )
    monkeypatch.setattr(
        main,
        "FlowPointService",
        lambda: _FakePointETL(events),
    )
    monkeypatch.setattr(
        main,
        "HoursReconciliationService",
        lambda: _FakeReconciliationETL(events),
    )

    assert main._run_flow_steps(None) == []
    assert events == ["identity", "points", "reconciliation"]


def test_flow_steps_do_not_request_points_when_identity_fails(monkeypatch):
    monkeypatch.setattr(main, "FLOW_ENABLED", True)
    monkeypatch.setattr(
        main,
        "FlowIdentityETL",
        _FailingIdentityETL,
    )

    def unexpected_point_service():
        raise AssertionError("Pontos não devem rodar sem identidades")

    monkeypatch.setattr(
        main,
        "FlowPointService",
        unexpected_point_service,
    )

    assert main._run_flow_steps(None) == [
        "Sincronização de colaboradores Flow"
    ]


class _FakeIdentityETL:
    def __init__(self, events):
        self.events = events

    def run(self):
        self.events.append("identity")
        return {
            "people": 2,
            "contracts": 2,
            "mapped": 1,
            "manual": 0,
            "unmapped_no_email": 0,
            "unmapped_no_match": 1,
            "ambiguous_email": 0,
        }


class _FakePointETL:
    def __init__(self, events):
        self.events = events

    def run(self):
        self.events.append("points")
        return {
            "people_requested": 1,
            "people_received": 1,
            "people_with_returned_days": 1,
            "days_replaced": 2,
            "marks_loaded": 4,
            "intervals_loaded": 2,
        }


class _FailingIdentityETL:
    def run(self):
        raise RuntimeError("Flow indisponível")


class _FakeReconciliationETL:
    def __init__(self, events):
        self.events = events

    def run(self):
        self.events.append("reconciliation")
        return {
            "records_evaluated": 2,
            "created": 2,
            "updated": 0,
            "unchanged": 0,
            "history_written": 2,
        }
