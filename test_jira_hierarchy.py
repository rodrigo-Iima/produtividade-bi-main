from __future__ import annotations

from datetime import datetime, timezone

import requests

from clients.jira_client import JiraClient
from config.settings import JIRA_EPIC_LINK_FIELD, JIRA_PLANNED_START_FIELD
from etl.jira import JiraService
from etl.jira_hierarchy import JiraHierarchyService


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_jira_search_retries_rate_limit_and_tracks_pages():
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "0.25"}),
        FakeResponse(
            200,
            {"issues": [{"key": "ZGT-1"}], "nextPageToken": "next"},
        ),
        FakeResponse(200, {"issues": [{"key": "ZGT-2"}]}),
    ])
    sleeps = []
    client = JiraClient(
        session=session,
        max_retries=1,
        sleep_fn=sleeps.append,
    )

    result = client.search("project = ZGT", fields=["summary"])

    assert [issue["key"] for issue in result] == ["ZGT-1", "ZGT-2"]
    assert client.last_metrics == {
        "requests": 3,
        "pages": 2,
        "records": 2,
        "retries": 1,
    }
    assert sleeps == [0.25]
    assert session.calls[2][2]["json"]["nextPageToken"] == "next"


def test_hierarchy_jql_is_epic_only_and_respects_scope_date():
    jql = JiraHierarchyService.build_epic_jql(
        ["ZGT", "ZG"],
        "2026-01-01",
    )
    assert jql == (
        'project in (ZGT, ZG) AND issuetype = Epic '
        'AND created >= "2026-01-01" ORDER BY created ASC'
    )


def test_incremental_hierarchy_jql_uses_updated_watermark():
    jql = JiraHierarchyService.build_epic_jql(
        ["ZGT"],
        "2026-01-01",
        updated_since=datetime(2026, 8, 18, 10, 30, tzinfo=timezone.utc),
    )
    assert jql == (
        'project in (ZGT) AND issuetype = Epic '
        'AND created >= "2026-01-01" '
        'AND updated >= "2026-08-18 10:30" ORDER BY updated ASC'
    )


def test_legacy_epic_link_field_expression_supports_custom_and_named_fields():
    assert JiraHierarchyService._field_expression("customfield_10014") == (
        "customfield_10014"
    )
    assert JiraHierarchyService._field_expression("Epic Link") == '"Epic Link"'


def test_jira_parent_and_planning_fields_are_normalized():
    service = JiraService()
    fields = {
        "parent": {"key": "ZGT-10"},
        "duedate": "2026-12-31",
        JIRA_PLANNED_START_FIELD: "2026-01-15",
    }
    assert service._parse_parent(fields) == ("ZGT-10", "parent")
    assert service._parse_day(fields["duedate"]).isoformat() == "2026-12-31"
    assert service._parse_day(fields[JIRA_PLANNED_START_FIELD]).isoformat() == (
        "2026-01-15"
    )
    assert service._parse_parent({JIRA_EPIC_LINK_FIELD: {"value": "ZGT-1"}}) == (
        "ZGT-1",
        "epic_link",
    )


def test_squad_filter_no_longer_drops_source_tickets():
    issue = {
        "key": "ZGT-99",
        "fields": {
            "summary": "Ticket SWAT preservado",
            "status": {"name": "Backlog"},
            "project": {"key": "ZGT", "name": "ZGT"},
            "issuetype": {"id": "10001", "name": "Task"},
            "created": "2026-01-01T10:00:00Z",
            "updated": "2026-01-01T10:00:00Z",
            "resolutiondate": None,
            "customfield_10431": {"value": "SWAT"},
            "customfield_10010": [],
        },
    }
    result = JiraService()._transform_issue(issue)
    assert result is not None
    assert result["ticket"].source_present is True
