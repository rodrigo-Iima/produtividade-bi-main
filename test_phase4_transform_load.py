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
            "issuetype": {"id": "10056", "name": "Melhoria"},
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
    assert result["ticket"].issue_type_id == "10056"
    assert result["ticket"].issue_type_name == "Melhoria"


def test_jira_transform_persists_original_estimate_seconds():
    issue = {
        "key": "ZG-102",
        "fields": {
            "summary": "Ticket estimado",
            "status": {"name": "Em andamento"},
            "project": {"key": "ZG", "name": "Projeto ZG"},
            "issuetype": {"id": "10056", "name": "Melhoria"},
            "created": "2026-04-01T10:00:00Z",
            "updated": "2026-04-02T10:00:00Z",
            "resolutiondate": None,
            "timetracking": {
                "originalEstimate": "2h",
                "originalEstimateSeconds": 7200,
            },
            JIRA_SQUAD_FIELD: {"value": "Squad de teste"},
            JIRA_SPRINT_FIELD: [],
            JIRA_CROSSING_FIELD: None,
        },
    }

    result = JiraService()._transform_issue(issue)
    assert result["ticket"].original_estimate_seconds == 7200


def test_jira_original_estimate_parser_keeps_unset_and_rejects_formatted_only():
    assert JiraService._parse_original_estimate_seconds({
        "timetracking": {"originalEstimateSeconds": 5400}
    }) == 5400
    assert JiraService._parse_original_estimate_seconds({
        "timeoriginalestimate": 3600
    }) == 3600
    assert JiraService._parse_original_estimate_seconds({
        "timetracking": {"originalEstimateSeconds": 0}
    }) == 0
    assert JiraService._parse_original_estimate_seconds({
        "timetracking": {"originalEstimate": "2h"}
    }) is None
    assert JiraService._parse_original_estimate_seconds({}) is None


def test_jira_transform_persists_real_sprint_completion_timestamp():
    issue = {
        "key": "ZG-101",
        "fields": {
            "summary": "Ticket de sprint encerrada",
            "status": {"name": "Concluído"},
            "project": {"key": "ZG", "name": "Projeto ZG"},
            "issuetype": {"id": "10056", "name": "Melhoria"},
            "created": "2026-07-01T10:00:00Z",
            "updated": "2026-07-20T18:00:00Z",
            "resolutiondate": None,
            JIRA_SQUAD_FIELD: {"value": "Squad de teste"},
            JIRA_SPRINT_FIELD: [{
                "id": "9239",
                "name": "Operadoras Sprint 26",
                "state": "closed",
                "startDate": "2026-06-30T14:23:07.960Z",
                "endDate": "2026-07-14T03:00:00.000Z",
                "completeDate": "2026-07-20T20:31:45.000Z",
            }],
            JIRA_CROSSING_FIELD: None,
        },
    }

    result = JiraService()._transform_issue(issue)
    sprint = result["sprints"][0]["sprint"]
    assert sprint.sprint_completed_at == datetime(
        2026, 7, 20, 20, 31, 45, tzinfo=timezone.utc
    )


if __name__ == "__main__":
    tests = [
        test_clockify_report_rows_are_deduplicated_by_entry_id,
        test_clockify_transform_deduplicates_tags_before_composite_load,
        test_clockify_transform_snapshots_squad_role_and_local_date,
        test_clockify_interval_overlap_excludes_entry_after_sprint_end,
        test_clockify_issue_key_source_is_classified_per_issue,
        test_jira_crossing_option_is_normalized_to_nullable_boolean,
        test_jira_transform_persists_crossing_flag_on_ticket,
        test_jira_transform_persists_original_estimate_seconds,
        test_jira_original_estimate_parser_keeps_unset_and_rejects_formatted_only,
        test_jira_transform_persists_real_sprint_completion_timestamp,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\nAll {len(tests)} Phase 4 tests passed.")
