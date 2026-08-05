"""Fetch Jira and Clockify data and produce the OKR analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from clients.clockify_client import ClockifyClient
from clients.jira_client import JiraClient
from config.settings import (
    CLOCKIFY_API_KEY,
    CLOCKIFY_DEV_TAG,
    CLOCKIFY_PAGE_SIZE,
    CLOCKIFY_WORKSPACE_ID,
    OKR_COMPLETED_STATUS,
    OKR_COMPLETED_STATUS_JQL,
    JIRA_EMAIL,
    JIRA_ESTIMATE_FIELD,
    JIRA_TOKEN,
    JIRA_URL,
    OKR_TIMEZONE,
    OKR_TICKET_TYPES,
    OKR_YEAR,
    build_okr_bugs_jql,
    execution_date,
)
from okr.domain import (
    BugTimeMatch,
    ClockifyEntry,
    JiraBug,
    MonthlyMetric,
    PeriodMetric,
    TicketClockifyRow,
    build_monthly_metrics,
    build_period_metrics,
    build_ticket_clockify_table,
    match_entries_to_bugs,
    parse_clockify_entries,
    parse_jira_bugs,
)
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AnalysisResult:
    bugs: tuple[JiraBug, ...]
    entries: tuple[ClockifyEntry, ...]
    matches: tuple[BugTimeMatch, ...]
    tickets_with_clockify: tuple[TicketClockifyRow, ...]
    monthly_metrics: tuple[MonthlyMetric, ...]
    period_metrics: tuple[PeriodMetric, ...]


@dataclass(frozen=True)
class RawInputs:
    """Raw API responses kept for source-field validation and snapshots."""

    jql: str
    as_of_date: date
    jira_issues: tuple[dict[str, Any], ...]
    clockify_entries: tuple[dict[str, Any], ...]


def run_analysis(
    *,
    jql: str | None = None,
    target_year: int = OKR_YEAR,
    timezone_name: str = OKR_TIMEZONE,
    estimate_field: str = JIRA_ESTIMATE_FIELD,
    as_of_date: date | None = None,
) -> AnalysisResult:
    """Run the complete API-only analysis for one calendar year."""
    effective_as_of_date = as_of_date or execution_date()
    effective_jql = jql or build_okr_bugs_jql(effective_as_of_date)
    inputs = fetch_inputs(
        jql=effective_jql,
        target_year=target_year,
        timezone_name=timezone_name,
        as_of_date=effective_as_of_date,
    )
    return analyze_inputs(
        inputs,
        target_year=target_year,
        timezone_name=timezone_name,
        estimate_field=estimate_field,
    )


def analyze_inputs(
    inputs: RawInputs,
    *,
    target_year: int,
    timezone_name: str,
    estimate_field: str,
) -> AnalysisResult:
    """Analyze already-fetched inputs without making network requests."""
    bugs = parse_jira_bugs(
        inputs.jira_issues,
        target_year=target_year,
        estimate_field=estimate_field,
        allowed_issue_types=OKR_TICKET_TYPES,
        completed_status=OKR_COMPLETED_STATUS,
    )

    entries = parse_clockify_entries(
        inputs.clockify_entries,
        target_year=target_year,
        timezone_name=timezone_name,
        required_tag_name=CLOCKIFY_DEV_TAG,
    )
    matches = match_entries_to_bugs(bugs, entries)
    monthly_metrics = build_monthly_metrics(
        bugs,
        matches,
        timezone_name=timezone_name,
    )
    tickets_with_clockify = build_ticket_clockify_table(bugs, matches)
    period_metrics = build_period_metrics(
        bugs,
        matches,
        target_year=target_year,
        as_of_date=inputs.as_of_date,
        timezone_name=timezone_name,
    )
    return AnalysisResult(
        bugs=tuple(bugs),
        entries=tuple(entries),
        matches=tuple(matches),
        tickets_with_clockify=tuple(tickets_with_clockify),
        monthly_metrics=tuple(monthly_metrics),
        period_metrics=tuple(period_metrics),
    )


def fetch_inputs(
    *,
    jql: str | None = None,
    target_year: int = OKR_YEAR,
    timezone_name: str = OKR_TIMEZONE,
    as_of_date: date | None = None,
) -> RawInputs:
    """Fetch Jira issues and Clockify entries without interpreting estimates."""
    _validate_configuration()
    effective_as_of_date = as_of_date or execution_date()
    effective_jql = jql or build_okr_bugs_jql(effective_as_of_date)
    estimate_fields = [
        "summary",
        "issuetype",
        "created",
        "status",
        "timeoriginalestimate",
        "timespent",
        "aggregatetimeoriginalestimate",
        "timetracking",
    ]
    if JIRA_ESTIMATE_FIELD not in estimate_fields:
        estimate_fields.append(JIRA_ESTIMATE_FIELD)

    jira_issues = JiraClient().search(
        jql=effective_jql,
        fields=estimate_fields,
        max_results=100,
    )
    clockify_entries = _fetch_clockify_entries(
        ClockifyClient(),
        target_year,
        as_of_date=effective_as_of_date,
        timezone_name=timezone_name,
    )
    return RawInputs(
        jql=effective_jql,
        as_of_date=effective_as_of_date,
        jira_issues=tuple(jira_issues),
        clockify_entries=tuple(clockify_entries),
    )


def raw_inputs_to_payload(
    inputs: RawInputs,
    *,
    jql: str | None = None,
    target_year: int | None = None,
) -> dict[str, Any]:
    """Serialize the unmodified API responses for the next validation step."""
    return {
        "definition": {
            "year": target_year,
            "as_of_date": inputs.as_of_date.isoformat(),
            "jql": jql or inputs.jql,
            "jira_issue_count": len(inputs.jira_issues),
            "clockify_entry_count": len(inputs.clockify_entries),
            "time_fields_interpretation": {
                "estimate": "timeoriginalestimate, seconds converted to hours",
                "jira_logged": "timespent, seconds converted to hours",
            },
        },
        "jira_issues": list(inputs.jira_issues),
        "clockify_entries": list(inputs.clockify_entries),
    }


def result_to_payload(
    result: AnalysisResult,
    *,
    jql: str,
    target_year: int,
    timezone_name: str,
    estimate_field: str,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Serialize the analysis with an independent payload for each ticket type."""
    effective_as_of_date = as_of_date or execution_date()
    definition = {
        "year": target_year,
        "as_of_date": effective_as_of_date.isoformat(),
        "timezone": timezone_name,
        "month_basis": "Jira ticket creation month",
        "jql": jql,
        "estimate_field": estimate_field,
        "ticket_types": list(OKR_TICKET_TYPES),
        "completed_status": OKR_COMPLETED_STATUS,
        "completed_status_jql": OKR_COMPLETED_STATUS_JQL,
        "multi_issue_entry_allocation": "equal_share",
        "clockify_required_tag": CLOCKIFY_DEV_TAG,
        "actual_time_rule": "sum(clockify_allocated_hours) for entries tagged Dev",
        "variation_rule": "spent_hours - estimate_hours; positive means above estimate",
        "actual_average_denominator": "Completed tickets with at least one matched Dev-tagged Clockify entry",
        "periods": {
            "baseline": f"{target_year}-01-01 through {target_year}-05-31",
            "excluded": f"{target_year}-06-01 through {target_year}-06-30",
            "current": f"{target_year}-07-01 through as_of_date",
        },
    }
    views = {
        issue_type.casefold(): _serialize_type_view(
            result,
            issue_type=issue_type,
            target_year=target_year,
            as_of_date=effective_as_of_date,
            timezone_name=timezone_name,
        )
        for issue_type in OKR_TICKET_TYPES
    }
    return {"definition": definition, "views": views}


def _serialize_type_view(
    result: AnalysisResult,
    *,
    issue_type: str,
    target_year: int,
    as_of_date: date,
    timezone_name: str,
) -> dict[str, Any]:
    """Build one independent view without consolidating ticket types."""
    tickets = tuple(
        bug for bug in result.bugs if bug.issue_type.casefold() == issue_type.casefold()
    )
    issue_keys = {ticket.issue_key for ticket in tickets}
    matches = tuple(match for match in result.matches if match.issue_key in issue_keys)
    match_entry_ids = {match.entry_id for match in matches}
    entries = tuple(entry for entry in result.entries if entry.entry_id in match_entry_ids)
    ticket_rows = tuple(
        row
        for row in result.tickets_with_clockify
        if row.issue_type.casefold() == issue_type.casefold()
    )
    monthly_metrics = build_monthly_metrics(
        tickets,
        matches,
        timezone_name=timezone_name,
    )
    period_metrics = build_period_metrics(
        tickets,
        matches,
        target_year=target_year,
        as_of_date=as_of_date,
        timezone_name=timezone_name,
    )
    return {
        "label": "Bugs" if issue_type.casefold() == "bug" else "Adaptativas",
        "issue_type": issue_type,
        "bugs": [
            {
                "issue_key": ticket.issue_key,
                "issue_type": ticket.issue_type,
                "summary": ticket.summary,
                "created_at": ticket.created_at.isoformat(),
                "estimate_hours": ticket.estimate_hours,
                "status": ticket.status,
                "jira_logged_hours": ticket.jira_logged_hours,
            }
            for ticket in tickets
        ],
        "entries": [
            {
                "entry_id": entry.entry_id,
                "started_at": entry.started_at.isoformat(),
                "duration_hours": round(entry.duration_hours, 4),
                "description": entry.description,
                "task_name": entry.task_name,
                "tag_names": list(entry.tag_names),
                "issue_sources": dict(entry.issue_sources),
            }
            for entry in entries
        ],
        "matches": [
            {
                "issue_key": match.issue_key,
                "entry_id": match.entry_id,
                "entry_hours": round(match.entry_hours, 4),
                "allocated_hours": round(match.allocated_hours, 4),
                "extraction_method": match.extraction_method,
            }
            for match in matches
        ],
        "tickets_with_clockify": [
            {
                "issue_key": row.issue_key,
                "issue_type": row.issue_type,
                "summary": row.summary,
                "created_at": row.created_at.isoformat(),
                "status": row.status,
                "estimate_hours": row.estimate_hours,
                "clockify_actual_hours": row.clockify_actual_hours,
                "clockify_entry_count": row.clockify_entry_count,
                "clockify_extraction_methods": list(row.clockify_extraction_methods),
                "jira_logged_hours": row.jira_logged_hours,
                "spent_hours": row.spent_hours,
                "spent_source": row.spent_source,
                "variation_hours": row.variation_hours,
            }
            for row in ticket_rows
        ],
        "monthly": [metric.__dict__ for metric in monthly_metrics],
        "periods": [metric.__dict__ for metric in period_metrics],
    }


def result_to_dashboard_payload(
    result: AnalysisResult,
    *,
    jql: str,
    target_year: int,
    timezone_name: str,
    estimate_field: str,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Serialize only the data required by the hosted dashboard."""
    payload = result_to_payload(
        result,
        jql=jql,
        target_year=target_year,
        timezone_name=timezone_name,
        estimate_field=estimate_field,
        as_of_date=as_of_date,
    )
    return {
        "definition": payload["definition"],
        "views": payload["views"],
    }


def write_payload(payload: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_clockify_entries(
    client: ClockifyClient,
    target_year: int,
    *,
    as_of_date: date,
    timezone_name: str,
) -> list[dict[str, Any]]:
    timezone = ZoneInfo(timezone_name)
    start_local = datetime(target_year, 1, 1, tzinfo=timezone)
    end_local = datetime(
        as_of_date.year,
        as_of_date.month,
        as_of_date.day,
        tzinfo=timezone,
    ) + timedelta(days=1, milliseconds=-1)
    start = start_local.astimezone(UTC)
    end = end_local.astimezone(UTC)
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
