"""Domain objects and deterministic transformations for the OKR metric."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
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
    status: str | None = None


@dataclass(frozen=True)
class ClockifyEntry:
    entry_id: str
    started_at: datetime
    duration_hours: float
    description: str
    task_name: str
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
) -> list[JiraBug]:
    """Normalize Jira search results and keep only Bugs created in the target year."""
    bugs: list[JiraBug] = []
    for issue in issues:
        fields = issue.get("fields") or {}
        issue_type = (fields.get("issuetype") or {}).get("name")
        if issue_type and issue_type.casefold() != "bug":
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
                status=(fields.get("status") or {}).get("name"),
            )
        )
    return sorted(bugs, key=lambda bug: (bug.created_at, bug.issue_key))


def parse_clockify_entries(
    entries: Iterable[dict[str, Any]],
    *,
    target_year: int,
    timezone_name: str,
) -> list[ClockifyEntry]:
    """Normalize detailed Clockify report rows and extract Jira keys."""
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
    timezone = ZoneInfo(timezone_name)
    matches_by_bug: dict[str, list[BugTimeMatch]] = defaultdict(list)
    for match in matches:
        matches_by_bug[match.issue_key].append(match)

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
            },
        )
        group["bugs_in_jira"] += 1
        bug_matches = matches_by_bug.get(bug.issue_key, [])
        if not bug_matches:
            continue

        group["bugs_with_clockify"] += 1
        group["matched_entries"] += len(bug_matches)
        actual_hours = sum(match.allocated_hours for match in bug_matches)
        group["actual"].append(actual_hours)
        if bug.estimate_hours is not None:
            group["estimate"].append(bug.estimate_hours)

    metrics: list[MonthlyMetric] = []
    for month, group in sorted(grouped.items()):
        actual_values = group["actual"]
        estimate_values = group["estimate"]
        avg_actual = _average(actual_values)
        avg_estimate = _average(estimate_values)
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
                avg_delta_hours=(
                    _rounded(avg_actual - avg_estimate)
                    if avg_actual is not None and avg_estimate is not None
                    else None
                ),
                actual_to_estimate_ratio=(
                    _rounded(avg_actual / avg_estimate)
                    if avg_actual is not None and avg_estimate not in (None, 0)
                    else None
                ),
            )
        )
    return metrics


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
        return float(value) / 3600
    except (TypeError, ValueError):
        return None


def _task_name(raw: dict[str, Any]) -> str:
    value = raw.get("taskName") or raw.get("task_name") or raw.get("task")
    if isinstance(value, dict):
        value = value.get("name")
    return str(value or "")


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _percentage(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0
