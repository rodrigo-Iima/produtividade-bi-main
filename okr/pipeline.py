"""Fetch Jira and Clockify data and produce the OKR analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from clients.clockify_client import ClockifyClient
from clients.jira_client import JiraClient
from config.settings import (
    CLOCKIFY_API_KEY,
    CLOCKIFY_PAGE_SIZE,
    CLOCKIFY_WORKSPACE_ID,
    JIRA_EMAIL,
    JIRA_ESTIMATE_FIELD,
    JIRA_TOKEN,
    JIRA_URL,
    OKR_BUGS_JQL,
    OKR_TIMEZONE,
    OKR_YEAR,
)
from okr.domain import (
    BugTimeMatch,
    ClockifyEntry,
    JiraBug,
    MonthlyMetric,
    build_monthly_metrics,
    match_entries_to_bugs,
    parse_clockify_entries,
    parse_jira_bugs,
)


@dataclass(frozen=True)
class AnalysisResult:
    bugs: tuple[JiraBug, ...]
    entries: tuple[ClockifyEntry, ...]
    matches: tuple[BugTimeMatch, ...]
    monthly_metrics: tuple[MonthlyMetric, ...]


def run_analysis(
    *,
    jql: str | None = None,
    target_year: int = OKR_YEAR,
    timezone_name: str = OKR_TIMEZONE,
    estimate_field: str = JIRA_ESTIMATE_FIELD,
) -> AnalysisResult:
    """Run the complete API-only analysis for one calendar year."""
    _validate_configuration()
    effective_jql = jql or OKR_BUGS_JQL

    raw_issues = JiraClient().search(
        jql=effective_jql,
        fields=[
            "summary",
            "issuetype",
            "created",
            "status",
            estimate_field,
            "timetracking",
        ],
        max_results=100,
    )
    bugs = parse_jira_bugs(
        raw_issues,
        target_year=target_year,
        estimate_field=estimate_field,
    )

    raw_entries = _fetch_clockify_entries(ClockifyClient(), target_year)
    entries = parse_clockify_entries(
        raw_entries,
        target_year=target_year,
        timezone_name=timezone_name,
    )
    matches = match_entries_to_bugs(bugs, entries)
    monthly_metrics = build_monthly_metrics(
        bugs,
        matches,
        timezone_name=timezone_name,
    )
    return AnalysisResult(
        bugs=tuple(bugs),
        entries=tuple(entries),
        matches=tuple(matches),
        monthly_metrics=tuple(monthly_metrics),
    )


def result_to_payload(
    result: AnalysisResult,
    *,
    jql: str,
    target_year: int,
    timezone_name: str,
    estimate_field: str,
) -> dict[str, Any]:
    """Serialize the analysis into a stable JSON contract for the future view."""
    return {
        "definition": {
            "year": target_year,
            "timezone": timezone_name,
            "month_basis": "Jira bug creation month",
            "jql": jql,
            "estimate_field": estimate_field,
            "multi_issue_entry_allocation": "equal_share",
            "actual_average_denominator": "Bugs with at least one matched Clockify entry",
        },
        "bugs": [
            {
                "issue_key": bug.issue_key,
                "summary": bug.summary,
                "created_at": bug.created_at.isoformat(),
                "estimate_hours": bug.estimate_hours,
                "status": bug.status,
            }
            for bug in result.bugs
        ],
        "entries": [
            {
                "entry_id": entry.entry_id,
                "started_at": entry.started_at.isoformat(),
                "duration_hours": round(entry.duration_hours, 4),
                "description": entry.description,
                "task_name": entry.task_name,
                "issue_sources": dict(entry.issue_sources),
            }
            for entry in result.entries
        ],
        "matches": [
            {
                "issue_key": match.issue_key,
                "entry_id": match.entry_id,
                "entry_hours": round(match.entry_hours, 4),
                "allocated_hours": round(match.allocated_hours, 4),
                "extraction_method": match.extraction_method,
            }
            for match in result.matches
        ],
        "monthly": [metric.__dict__ for metric in result.monthly_metrics],
    }


def write_payload(payload: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_clockify_entries(client: ClockifyClient, target_year: int) -> list[dict[str, Any]]:
    start = datetime(target_year, 1, 1, tzinfo=UTC)
    end = datetime(target_year + 1, 1, 1, tzinfo=UTC) - timedelta(milliseconds=1)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.999Z")

    entries: list[dict[str, Any]] = []
    page = 1
    while True:
        report = client.get_detailed_report(
            start_str,
            end_str,
            page=page,
            page_size=CLOCKIFY_PAGE_SIZE,
        )
        page_entries = report.get("timeentries") or []
        if not page_entries:
            break
        entries.extend(page_entries)
        if len(page_entries) < CLOCKIFY_PAGE_SIZE:
            break
        page += 1
    return entries


def _validate_configuration() -> None:
    missing = [
        name
        for name, value in (
            ("JIRA_URL", JIRA_URL),
            ("JIRA_EMAIL", JIRA_EMAIL),
            ("JIRA_TOKEN", JIRA_TOKEN),
            ("CLOCKIFY_API_KEY", CLOCKIFY_API_KEY),
            ("CLOCKIFY_WORKSPACE_ID", CLOCKIFY_WORKSPACE_ID),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Configuração de API incompleta. Defina no .env: " + ", ".join(missing)
        )
