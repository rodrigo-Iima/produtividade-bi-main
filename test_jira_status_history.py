from datetime import datetime, timezone

from etl.jira_status_history import real_end_at, real_start_at
from etl.jira_sprint_changelog import SprintChangelogETL


def test_single_changelog_read_can_materialize_status_transitions_and_authorship():
    histories = [{
        "id": "1001",
        "created": "2026-07-10T12:00:00.000+0000",
        "author": {"accountId": "acc-1", "displayName": "Ana"},
        "items": [
            {
                "fieldId": "status",
                "from": "1",
                "fromString": "Backlog",
                "to": "3",
                "toString": "Em andamento",
            },
            {
                "fieldId": "Sprint",
                "field": "Sprint",
                "from": None,
                "to": "42",
                "toString": "Sprint 42 [id=42,state=ACTIVE]",
            },
        ],
    }]

    etl = SprintChangelogETL(max_workers=1, client=object())
    transitions = etl._extract_status_transitions("ZGT-1", histories)

    assert transitions == [{
        "issue_key": "ZGT-1",
        "transition_key": "jira:1001:0",
        "transition_at": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        "from_status_id": "1",
        "from_status_name": "Backlog",
        "to_status_id": "3",
        "to_status_name": "Em andamento",
        "author_account_id": "acc-1",
        "author_name": "Ana",
        "source_present": True,
    }]
    assert etl._extract_sprint_changes(histories)[0]["sprint_id"] == 42


def test_transition_key_without_history_id_is_deterministic():
    item = {"from": "1", "to": "3", "fromString": "Backlog", "toString": "Dev"}
    first = SprintChangelogETL._transition_key(
        "ZGT-1", "", 0, datetime(2026, 1, 1, tzinfo=timezone.utc), item
    )
    second = SprintChangelogETL._transition_key(
        "ZGT-1", "", 0, datetime(2026, 1, 1, tzinfo=timezone.utc), item
    )
    assert first == second
    assert first.startswith("hash:")


def test_real_start_and_end_preserve_reopen_history():
    transitions = [
        {
            "transition_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            "to_status_name": "Em andamento",
        },
        {
            "transition_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
            "to_status_name": "Concluído",
        },
        {
            "transition_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
            "to_status_name": "Em andamento",
        },
        {
            "transition_at": datetime(2026, 7, 9, tzinfo=timezone.utc),
            "to_status_name": "Concluído",
        },
    ]
    assert real_start_at(transitions) == transitions[0]["transition_at"]
    assert real_end_at(transitions) == transitions[-1]["transition_at"]
    assert real_end_at(
        transitions,
        resolution_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    ) == datetime(2026, 7, 10, tzinfo=timezone.utc)


def test_reopened_ticket_has_no_current_real_end_without_resolution():
    transitions = [
        {
            "transition_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
            "to_status_name": "Concluído",
        },
        {
            "transition_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
            "to_status_name": "Em andamento",
        },
    ]
    assert real_end_at(transitions) is None


def test_reopened_ticket_ignores_stale_resolution_date():
    transitions = [
        {
            "transition_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
            "to_status_name": "Concluído",
        },
        {
            "transition_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
            "to_status_name": "Em andamento",
        },
    ]
    assert real_end_at(
        transitions,
        resolution_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    ) is None


def test_execution_start_is_limited_to_em_andamento():
    transition = {"to_status_id": "99", "to_status_name": "Travado"}
    mapping = {"99": {"starts_execution": True, "is_completion": False}}
    assert real_start_at([{
        **transition,
        "transition_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }], mappings=mapping) is None
