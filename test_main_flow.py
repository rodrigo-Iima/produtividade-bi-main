"""Tests for Flow orchestration inside the main ETL pipeline."""

import main


def test_flow_steps_can_be_disabled(monkeypatch, capsys):
    monkeypatch.setattr(main, "FLOW_ENABLED", False)

    assert main._run_flow_steps(None) == []
    assert "FLOW_ENABLED=false" in capsys.readouterr().out


def test_flow_steps_can_collect_points_from_stored_ids(monkeypatch):
    events = []
    monkeypatch.setattr(main, "FLOW_ENABLED", True)
    monkeypatch.setattr(main, "FLOW_IDENTITY_SYNC_ENABLED", False)
    monkeypatch.setattr(main, "FLOW_POINTS_INCLUDE_UNMAPPED", True)
    monkeypatch.setattr(main, "FlowClient", _FakeFlowClient)
    monkeypatch.setattr(
        main,
        "FlowIdentityETL",
        lambda client=None: _FailingIdentityETL(),
    )

    def point_service(client=None, include_unmapped=False):
        assert include_unmapped is True
        return _FakePointETL(events)

    monkeypatch.setattr(main, "FlowPointService", point_service)
    monkeypatch.setattr(
        main,
        "HoursReconciliationService",
        lambda: _FakeReconciliationETL(events),
    )

    assert main._run_flow_steps(None) == []
    assert events == ["points", "reconciliation"]


def test_flow_steps_run_identity_before_points(monkeypatch):
    events = []
    monkeypatch.setattr(main, "FLOW_ENABLED", True)
    monkeypatch.setattr(main, "FlowClient", _FakeFlowClient)
    monkeypatch.setattr(
        main,
        "FlowIdentityETL",
        lambda client=None: _FakeIdentityETL(events),
    )
    monkeypatch.setattr(
        main,
        "FlowPointService",
        lambda client=None, include_unmapped=False: _FakePointETL(events),
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
    monkeypatch.setattr(main, "FlowClient", _FakeFlowClient)
    monkeypatch.setattr(
        main,
        "FlowIdentityETL",
        _FailingIdentityETL,
    )

    def unexpected_point_service(client=None):
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


class _FakeFlowClient:
    def close(self):
        pass


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
    def __init__(self, client=None):
        pass

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
