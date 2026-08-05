"""Domain objects and deterministic transformations for the OKR metric."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import math
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ISSUE_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class JiraBug:
    issue_key: str
    summary: str
    created_at: datetime
    estimate_hours: float | None
    issue_type: str = "Bug"
    status: str | None = None
    jira_logged_hours: float | None = None


@dataclass(frozen=True)
class ClockifyEntry:
    entry_id: str
    started_at: datetime
    duration_hours: float
    description: str
    task_name: str
    tag_names: tuple[str, ...]
    issue_sources: tuple[tuple[str, str], ...]

    @property
    def issue_keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.issue_sources)


@dataclass(frozen=True)
class BugTimeMatch:
    issue_key: str
    entry_id: str
    entry_hours: float
    allocated_hours: float
    extraction_method: str


@dataclass(frozen=True)
class MonthlyMetric:
    month: str
    bugs_in_jira: int
    bugs_with_clockify: int
    coverage_pct: float
    matched_entries: int
    total_actual_hours: float
    avg_estimate_hours: float | None
    avg_actual_hours: float | None
    avg_delta_hours: float | None
    actual_to_estimate_ratio: float | None


@dataclass(frozen=True)
class PeriodMetric:
    period: str
    label: str
    start_date: str
    end_date: str
    bugs_in_jira: int
    bugs_with_estimate: int
    bugs_with_clockify: int
    bugs_with_variation: int
    coverage_pct: float
    matched_entries: int
    avg_estimate_hours: float | None
    avg_actual_hours: float | None
    avg_delta_hours: float | None


@dataclass(frozen=True)
class TicketClockifyRow:
    """One Jira ticket with at least one related Clockify entry."""

    issue_key: str
    issue_type: str
    summary: str
    created_at: datetime
    status: str | None
    estimate_hours: float | None
    clockify_actual_hours: float
    jira_logged_hours: float | None
    spent_hours: float
    spent_source: str
    variation_hours: float | None
    clockify_entry_count: int
    clockify_extraction_methods: tuple[str, ...]


def parse_datetime(value: Any) -> datetime:
    """Parse an ISO timestamp and normalize naive values to UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError(f"Timestamp inválido: {value!r}")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_jira_bugs(
    issues: Iterable[dict[str, Any]],
    *,
    target_year: int,
    estimate_field: str,
    allowed_issue_types: Iterable[str] = ("Bug", "Adaptativa"),
    completed_status: str = "Concluído",
) -> list[JiraBug]:
    """Normalize completed Jira tickets in the configured OKR scope."""
    normalized_types = {value.casefold() for value in allowed_issue_types}
    bugs: list[JiraBug] = []
    for issue in issues:
        fields = issue.get("fields") or {}
        issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip()
        if not issue_type or issue_type.casefold() not in normalized_types:
            continue
        status = str((fields.get("status") or {}).get("name") or "").strip()
        if not status or status.casefold() != completed_status.casefold():
            continue

        issue_key = str(issue.get("key") or "").strip().upper()
        if not issue_key:
            continue
        created_at = parse_datetime(fields.get("created"))
        if created_at.year != target_year:
            continue

        bugs.append(
            JiraBug(
                issue_key=issue_key,
                summary=str(fields.get("summary") or ""),
                created_at=created_at,
                estimate_hours=_estimate_hours(fields, estimate_field),
                issue_type=issue_type,
                status=status,
                jira_logged_hours=_jira_logged_hours(fields),
            )
        )
    return sorted(bugs, key=lambda bug: (bug.created_at, bug.issue_key))


def parse_clockify_entries(
    entries: Iterable[dict[str, Any]],
    *,
    target_year: int,
    timezone_name: str,
    required_tag_name: str | None = None,
) -> list[ClockifyEntry]:
    """Normalize Clockify rows, optionally keeping one exact tag by name."""
    timezone = ZoneInfo(timezone_name)
    normalized: list[ClockifyEntry] = []
    for raw in entries:
        interval = raw.get("timeInterval") or {}
        start_value = interval.get("start")
        end_value = interval.get("end")
        if not start_value or not end_value:
            continue

        started_at = parse_datetime(start_value)
        ended_at = parse_datetime(end_value)
        duration_seconds = max(0, round((ended_at - started_at).total_seconds()))
        local_date = started_at.astimezone(timezone).date()
        if local_date.year != target_year or duration_seconds <= 0:
            continue

        tag_names = _tag_names(raw)
        if required_tag_name and not any(
            tag.casefold() == required_tag_name.casefold() for tag in tag_names
        ):
            continue

        description = str(raw.get("description") or "")
        task_name = _task_name(raw)
        sources = extract_issue_sources(description, task_name)
        normalized.append(
            ClockifyEntry(
                entry_id=str(raw.get("_id") or raw.get("id") or "").strip(),
                started_at=started_at,
                duration_hours=duration_seconds / 3600,
                description=description,
                task_name=task_name,
                tag_names=tag_names,
                issue_sources=tuple(sorted(sources.items())),
            )
        )
    return [entry for entry in normalized if entry.entry_id]


def extract_issue_sources(description: str | None, task_name: str | None) -> dict[str, str]:
    """Return each Jira key once, preserving where it was found."""
    sources: dict[str, set[str]] = defaultdict(set)
    for source_name, text in (("description", description), ("task_name", task_name)):
        if not text:
            continue
        for match in ISSUE_KEY_PATTERN.findall(text):
            sources[match.upper()].add(source_name)

    result: dict[str, str] = {}
    for issue_key, found_in in sources.items():
        if found_in == {"description"}:
            result[issue_key] = "description"
        elif found_in == {"task_name"}:
            result[issue_key] = "task_name"
        else:
            result[issue_key] = "description_and_task"
    return result


def match_entries_to_bugs(
    bugs: Iterable[JiraBug],
    entries: Iterable[ClockifyEntry],
) -> list[BugTimeMatch]:
    """Relate entries to known Bugs without double-counting multi-key entries."""
    known_keys = {bug.issue_key for bug in bugs}
    matches: list[BugTimeMatch] = []
    for entry in entries:
        linked = [
            (issue_key, method)
            for issue_key, method in entry.issue_sources
            if issue_key in known_keys
        ]
        if not linked:
            continue

        allocated_hours = entry.duration_hours / len(linked)
        for issue_key, method in linked:
            matches.append(
                BugTimeMatch(
                    issue_key=issue_key,
                    entry_id=entry.entry_id,
                    entry_hours=entry.duration_hours,
                    allocated_hours=allocated_hours,
                    extraction_method=method,
                )
            )
    return matches


def build_monthly_metrics(
    bugs: Iterable[JiraBug],
    matches: Iterable[BugTimeMatch],
    *,
    timezone_name: str,
) -> list[MonthlyMetric]:
    """Aggregate one row per Jira-created month, with matched Bugs as denominator."""
    bugs = list(bugs)
    timezone = ZoneInfo(timezone_name)
    tickets = build_ticket_clockify_table(bugs, matches)
    tickets_by_key = {ticket.issue_key: ticket for ticket in tickets}

    grouped: dict[str, dict[str, Any]] = {}
    for bug in bugs:
        month = bug.created_at.astimezone(timezone).strftime("%Y-%m")
        group = grouped.setdefault(
            month,
            {
                "bugs_in_jira": 0,
                "bugs_with_clockify": 0,
                "matched_entries": 0,
                "actual": [],
                "estimate": [],
                "paired_actual": [],
                "paired_estimate": [],
                "variation": [],
            },
        )
        group["bugs_in_jira"] += 1
        if _is_valid_hours(bug.estimate_hours):
            group["estimate"].append(bug.estimate_hours)

        ticket = tickets_by_key.get(bug.issue_key)
        if ticket is None:
            continue

        group["bugs_with_clockify"] += 1
        group["matched_entries"] += ticket.clockify_entry_count
        group["actual"].append(ticket.spent_hours)
        if _is_valid_hours(bug.estimate_hours):
            group["paired_actual"].append(ticket.spent_hours)
            group["paired_estimate"].append(bug.estimate_hours)
            group["variation"].append(ticket.variation_hours)

    metrics: list[MonthlyMetric] = []
    for month, group in sorted(grouped.items()):
        actual_values = group["actual"]
        estimate_values = group["estimate"]
        paired_actual_values = group["paired_actual"]
        paired_estimate_values = group["paired_estimate"]
        variation_values = group["variation"]
        avg_actual = _average(actual_values)
        avg_estimate = _average(estimate_values)
        avg_paired_actual = _average(paired_actual_values)
        avg_paired_estimate = _average(paired_estimate_values)
        metrics.append(
            MonthlyMetric(
                month=month,
                bugs_in_jira=group["bugs_in_jira"],
                bugs_with_clockify=group["bugs_with_clockify"],
                coverage_pct=_percentage(
                    group["bugs_with_clockify"], group["bugs_in_jira"]
                ),
                matched_entries=group["matched_entries"],
                total_actual_hours=round(sum(actual_values), 4),
                avg_estimate_hours=_rounded(avg_estimate),
                avg_actual_hours=_rounded(avg_actual),
                avg_delta_hours=_rounded(_average(variation_values)),
                actual_to_estimate_ratio=(
                    _rounded(avg_paired_actual / avg_paired_estimate)
                    if avg_paired_actual is not None
                    and avg_paired_estimate not in (None, 0)
                    else None
                ),
            )
        )
    return metrics


def build_period_metrics(
    bugs: Iterable[JiraBug],
    matches: Iterable[BugTimeMatch],
    *,
    target_year: int,
    as_of_date: date,
    timezone_name: str,
) -> list[PeriodMetric]:
    """Build ticket-weighted baseline and current-period KPI cohorts."""
    bug_list = list(bugs)
    tickets = build_ticket_clockify_table(bug_list, matches)
    timezone = ZoneInfo(timezone_name)
    definitions = (
        (
            "baseline",
            "Base jan–mai",
            date(target_year, 1, 1),
            date(target_year, 6, 1),
        ),
        (
            "current",
            "Atual desde 01/07",
            date(target_year, 7, 1),
            as_of_date + timedelta(days=1),
        ),
    )
    return [
        _build_period_metric(
            period=period,
            label=label,
            start_date=start_date,
            end_date_exclusive=end_date,
            bugs=bug_list,
            tickets=tickets,
            timezone=timezone,
        )
        for period, label, start_date, end_date in definitions
    ]


def _build_period_metric(
    *,
    period: str,
    label: str,
    start_date: date,
    end_date_exclusive: date,
    bugs: list[JiraBug],
    tickets: list[TicketClockifyRow],
    timezone: ZoneInfo,
) -> PeriodMetric:
    period_bugs = [
        bug
        for bug in bugs
        if start_date <= bug.created_at.astimezone(timezone).date() < end_date_exclusive
    ]
    bug_keys = {bug.issue_key for bug in period_bugs}
    period_tickets = [ticket for ticket in tickets if ticket.issue_key in bug_keys]
    estimate_values = [
        bug.estimate_hours
        for bug in period_bugs
        if _is_valid_hours(bug.estimate_hours)
    ]
    actual_values = [ticket.spent_hours for ticket in period_tickets]
    variation_values = [
        ticket.variation_hours
        for ticket in period_tickets
        if ticket.variation_hours is not None
    ]
    end_date = max(start_date, end_date_exclusive - timedelta(days=1))
    return PeriodMetric(
        period=period,
        label=label,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        bugs_in_jira=len(period_bugs),
        bugs_with_estimate=len(estimate_values),
        bugs_with_clockify=len(period_tickets),
        bugs_with_variation=len(variation_values),
        coverage_pct=_percentage(len(period_tickets), len(period_bugs)),
        matched_entries=sum(ticket.clockify_entry_count for ticket in period_tickets),
        avg_estimate_hours=_rounded(_average(estimate_values)),
        avg_actual_hours=_rounded(_average(actual_values)),
        avg_delta_hours=_rounded(_average(variation_values)),
    )


def build_ticket_clockify_table(
    bugs: Iterable[JiraBug],
    matches: Iterable[BugTimeMatch],
) -> list[TicketClockifyRow]:
    """Build one joined row per Jira Bug with mapped Clockify time."""
    bugs_by_key = {bug.issue_key: bug for bug in bugs}
    matches_by_key: dict[str, list[BugTimeMatch]] = defaultdict(list)
    for match in matches:
        matches_by_key[match.issue_key].append(match)

    rows: list[TicketClockifyRow] = []
    for issue_key, ticket_matches in matches_by_key.items():
        bug = bugs_by_key.get(issue_key)
        if bug is None:
            continue
        valid_matches = [
            match
            for match in ticket_matches
            if _is_valid_hours(match.allocated_hours, allow_zero=False)
        ]
        if not valid_matches:
            continue
        clockify_hours = sum(match.allocated_hours for match in valid_matches)
        spent_hours = round(clockify_hours, 4)
        rows.append(
            TicketClockifyRow(
                issue_key=bug.issue_key,
                issue_type=bug.issue_type,
                summary=bug.summary,
                created_at=bug.created_at,
                status=bug.status,
                estimate_hours=bug.estimate_hours,
                clockify_actual_hours=round(clockify_hours, 4),
                jira_logged_hours=bug.jira_logged_hours,
                spent_hours=spent_hours,
                spent_source="clockify_dev",
                variation_hours=_variation_hours(
                    spent_hours=spent_hours,
                    estimate_hours=bug.estimate_hours,
                ),
                clockify_entry_count=len(valid_matches),
                clockify_extraction_methods=tuple(
                    sorted({match.extraction_method for match in valid_matches})
                ),
            )
        )
    sorted_rows = sorted(
        rows,
        key=lambda row: (row.created_at, row.issue_key),
        reverse=True,
    )
    _validate_ticket_clockify_rows(sorted_rows)
    return sorted_rows


def _validate_ticket_clockify_rows(rows: Iterable[TicketClockifyRow]) -> None:
    """Fail fast if a joined row could produce an invalid OKR metric."""
    for row in rows:
        if not row.issue_key:
            raise ValueError("Ticket relacionado sem issue_key")
        if not _is_valid_hours(row.clockify_actual_hours, allow_zero=False):
            raise ValueError(f"Clockify inválido para {row.issue_key}")
        if row.estimate_hours is not None and not _is_valid_hours(
            row.estimate_hours
        ):
            raise ValueError(f"Estimativa Jira inválida para {row.issue_key}")
        if row.jira_logged_hours is not None and not _is_valid_hours(
            row.jira_logged_hours
        ):
            raise ValueError(f"Timespent Jira inválido para {row.issue_key}")

        if (
            row.spent_hours != row.clockify_actual_hours
            or row.spent_source != "clockify_dev"
        ):
            raise ValueError(f"Fonte de tempo inconsistente para {row.issue_key}")

        expected_variation = _variation_hours(
            spent_hours=row.spent_hours,
            estimate_hours=row.estimate_hours,
        )
        if row.variation_hours != expected_variation:
            raise ValueError(f"Variação inconsistente para {row.issue_key}")


def _estimate_hours(fields: dict[str, Any], estimate_field: str) -> float | None:
    value = fields.get(estimate_field)
    if value is None:
        tracking = fields.get("timetracking") or {}
        value = tracking.get("originalEstimateSeconds")
    if isinstance(value, dict):
        value = value.get("originalEstimateSeconds") or value.get("seconds")
    if value in (None, ""):
        return None
    try:
        hours = float(value) / 3600
    except (TypeError, ValueError):
        return None
    return hours if _is_valid_hours(hours, allow_zero=False) else None


def _jira_logged_hours(fields: dict[str, Any]) -> float | None:
    """Read Jira's logged time, whose REST value is expressed in seconds."""
    value = fields.get("timespent")
    if value is None:
        tracking = fields.get("timetracking") or {}
        value = tracking.get("timeSpentSeconds")
        if value is None:
            value = tracking.get("timespent")
    if isinstance(value, dict):
        value = value.get("timeSpentSeconds") or value.get("seconds")
    if value in (None, ""):
        return None
    try:
        hours = float(value) / 3600
    except (TypeError, ValueError):
        return None
    return hours if _is_valid_hours(hours) else None


def _variation_hours(*, spent_hours: float, estimate_hours: float | None) -> float | None:
    """Positive values mean that spent time exceeded the estimate."""
    if estimate_hours is None:
        return None
    return round(spent_hours - estimate_hours, 4)


def _is_valid_hours(value: float | None, *, allow_zero: bool = True) -> bool:
    """Accept only finite, non-negative hour values for aggregation."""
    if value is None or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(value):
        return False
    return value >= 0 if allow_zero else value > 0


def _task_name(raw: dict[str, Any]) -> str:
    value = raw.get("taskName") or raw.get("task_name") or raw.get("task")
    if isinstance(value, dict):
        value = value.get("name")
    return str(value or "")


def _tag_names(raw: dict[str, Any]) -> tuple[str, ...]:
    values = raw.get("tags") or raw.get("tagNames") or []
    if isinstance(values, str):
        values = [values]
    names: set[str] = set()
    for value in values:
        name = value.get("name") if isinstance(value, dict) else value
        if name and str(name).strip():
            names.add(str(name).strip())
    return tuple(sorted(names, key=str.casefold))


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _percentage(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0
