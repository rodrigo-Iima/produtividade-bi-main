"""Unit tests for Phase 4 transformations that do not require PostgreSQL."""

from datetime import date, datetime, timezone

from etl.clockify import ClockifyService
from etl.jira import JiraService
from config.settings import JIRA_CROSSING_FIELD, JIRA_SPRINT_FIELD, JIRA_SQUAD_FIELD


def test_clockify_report_rows_are_deduplicated_by_entry_id():
    rows = [
        {"_id": "entry-1", "description": "first"},
        {"_id": "entry-1", "description": "duplicate"},
        {"_id": "entry-2", "description": "second"},
    ]
    result = ClockifyService._deduplicate_entries(rows)
    assert [row["_id"] for row in result] == ["entry-1", "entry-2"]


def test_clockify_transform_deduplicates_tags_before_composite_load():
    raw = {
        "_id": "entry-1",
        "userId": "user-1",
        "projectName": "Projeto",
        "tags": [{"name": "Dev"}, {"name": "dev"}],
        "timeInterval": {
            "start": "2026-04-03T10:00:00Z",
            "end": "2026-04-03T11:00:00Z",
        },
    }
    fact, tags = ClockifyService()._transform_entry(
        raw,
        {"user-1": "Desenvolvedor"},
        {},
        {"dev": 8},
        {("desenvolvedor", 8): "Dentro do Foco"},
    )
    assert fact.duration_seconds == 3600
    assert len(tags) == 1
    assert tags[0].tag_id == 8


def test_clockify_transform_snapshots_squad_role_and_local_date():
    raw = {
        "_id": "entry-local-date",
        "userId": "user-1",
        "projectName": "Projeto",
        "tags": [],
        "timeInterval": {
            "start": "2026-04-03T02:30:00Z",
            "end": "2026-04-03T03:30:00Z",
        },
    }
    fact, _ = ClockifyService()._transform_entry(
        raw,
        {"user-1": "Desenvolvedor"},
        {},
        {},
        {},
        {
            "user-1": {
                "squad_id": 7,
                "squad_name": "Núcleo",
                "papel": "Desenvolvedor",
            }
        },
    )
    assert fact.squad_id_at_entry == 7
    assert fact.squad_name_at_entry == "Núcleo"
    assert fact.papel_at_entry == "Desenvolvedor"
    assert fact.entry_date_local == date(2026, 4, 2)


def test_clockify_interval_overlap_excludes_entry_after_sprint_end():
    entry = type(
        "Entry",
        (),
        {
            "started_at": datetime(2026, 4, 17, 10, tzinfo=timezone.utc),
            "ended_at": datetime(2026, 4, 17, 11, tzinfo=timezone.utc),
        },
    )()
    sprint = {
        "sprint_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "sprint_end": datetime(2026, 4, 17, tzinfo=timezone.utc),
    }
    assert ClockifyService._interval_overlaps(entry, sprint) is False


def test_clockify_issue_key_source_is_classified_per_issue():
    sources = ClockifyService._extract_issue_keys_with_sources(
        "Validar ZG-100 e ZGT-200",
        "ZG-100 - ajuste",
    )
    assert sources == {
        "ZG-100": {"description", "task_name"},
        "ZGT-200": {"description"},
    }
    assert ClockifyService._extraction_method(sources["ZG-100"]) == (
        "description_and_task"
    )
    assert ClockifyService._extraction_method(sources["ZGT-200"]) == "description"
    assert ClockifyService._extraction_method({"task_name"}) == "task_name"


def test_jira_crossing_option_is_normalized_to_nullable_boolean():
    assert JiraService._parse_crossing_flag({"value": "Sim"}) is True
    assert JiraService._parse_crossing_flag({"value": "Não"}) is False
    assert JiraService._parse_crossing_flag(None) is None
    assert JiraService._parse_crossing_flag({"value": "Outra opção"}) is None


def test_jira_transform_persists_crossing_flag_on_ticket():
    issue = {
        "key": "ZG-100",
        "fields": {
            "summary": "Ticket de teste",
            "status": {"name": "Em andamento"},
            "project": {"key": "ZG", "name": "Projeto ZG"},
            "created": "2026-04-01T10:00:00Z",
            "updated": "2026-04-02T10:00:00Z",
            "resolutiondate": None,
            JIRA_SQUAD_FIELD: {"value": "Squad de teste"},
            JIRA_SPRINT_FIELD: [],
            JIRA_CROSSING_FIELD: {"value": "Sim"},
        },
    }
    result = JiraService()._transform_issue(issue)
    assert result["ticket"].atravessamento_flag is True


if __name__ == "__main__":
    tests = [
        test_clockify_report_rows_are_deduplicated_by_entry_id,
        test_clockify_transform_deduplicates_tags_before_composite_load,
        test_clockify_transform_snapshots_squad_role_and_local_date,
        test_clockify_interval_overlap_excludes_entry_after_sprint_end,
        test_clockify_issue_key_source_is_classified_per_issue,
        test_jira_crossing_option_is_normalized_to_nullable_boolean,
        test_jira_transform_persists_crossing_flag_on_ticket,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\nAll {len(tests)} Phase 4 tests passed.")
