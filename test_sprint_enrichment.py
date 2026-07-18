"""Unit tests for sprint enrichment business logic (no DB required)."""

from datetime import datetime
from types import SimpleNamespace

from etl.jira_sprint_enrichment import (
    compute_planejado_no_inicio,
    compute_sprint_entrada_at,
    sprint_matches,
)
from etl.jira_sprint_changelog import SprintChangelogETL
from etl.sprint_scope import sprint_is_in_scope


def _changelog(**kwargs):
    defaults = {
        "change_type": "added",
        "changed_at": datetime(2026, 1, 5, 10, 0, 0),
        "sprint_id": 100,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_sprint_entrada_uses_earliest_changelog_add():
    created = datetime(2026, 1, 1, 9, 0, 0)
    entries = [
        _changelog(changed_at=datetime(2026, 1, 8, 12, 0, 0)),
        _changelog(changed_at=datetime(2026, 1, 3, 12, 0, 0)),
    ]
    result = compute_sprint_entrada_at(created, 100, entries)
    assert result == datetime(2026, 1, 3, 12, 0, 0)


def test_sprint_entrada_fallback_to_created_when_no_changelog():
    created = datetime(2026, 1, 2, 9, 0, 0)
    result = compute_sprint_entrada_at(created, 100, [])
    assert result == created


def test_sprint_entrada_ignores_removed_changes():
    created = datetime(2026, 1, 1, 9, 0, 0)
    entries = [_changelog(change_type="removed")]
    result = compute_sprint_entrada_at(created, 100, entries)
    assert result == created


def test_planejado_no_inicio_on_time():
    entrada = datetime(2026, 1, 5, 10, 0, 0)
    sprint_start = datetime(2026, 1, 6, 17, 45, 51)
    assert compute_planejado_no_inicio(entrada, sprint_start) is True


def test_planejado_no_inicio_late():
    entrada = datetime(2026, 1, 8, 10, 0, 0)
    sprint_start = datetime(2026, 1, 6, 17, 45, 51)
    assert compute_planejado_no_inicio(entrada, sprint_start) is False


def test_planejado_no_inicio_exact_start_counts_as_planejado():
    ts = datetime(2026, 1, 6, 17, 45, 51)
    assert compute_planejado_no_inicio(ts, ts) is True


def test_sprint_matches_by_id():
    entry = _changelog(sprint_id=42)
    assert sprint_matches(entry, 42) is True


def test_parse_multiple_sprint_descriptors():
    result = SprintChangelogETL._parse_sprint_change(
        None,
        "Sprint A [id=1,state=ACTIVE], Sprint B [id=2,state=FUTURE]",
    )
    assert result == [
        {"sprint_id": 1, "sprint_name": "Sprint A"},
        {"sprint_id": 2, "sprint_name": "Sprint B"},
    ]


def test_parse_historical_sprint_id_from_changelog():
    result = SprintChangelogETL._parse_sprint_change(
        "9191",
        "ZGT-2026.T1.04 [id=9191,state=CLOSED]",
    )
    assert result == [
        {"sprint_id": 9191, "sprint_name": "ZGT-2026.T1.04"},
    ]


def test_sprint_scope_accepts_active_and_closed_2026_sprints():
    now = datetime(2026, 7, 17, 12, 0, 0)
    assert sprint_is_in_scope(datetime(2026, 1, 1, 12, 0, 0), "active", now)
    assert sprint_is_in_scope(datetime(2026, 6, 22, 12, 0, 0), "closed", now)
    assert not sprint_is_in_scope(datetime(2026, 8, 4, 0, 0, 0), "future", now)
    assert not sprint_is_in_scope(datetime(2025, 12, 31, 12, 0, 0), "closed", now)


if __name__ == "__main__":
    tests = [
        test_sprint_entrada_uses_earliest_changelog_add,
        test_sprint_entrada_fallback_to_created_when_no_changelog,
        test_sprint_entrada_ignores_removed_changes,
        test_planejado_no_inicio_on_time,
        test_planejado_no_inicio_late,
        test_planejado_no_inicio_exact_start_counts_as_planejado,
        test_sprint_matches_by_id,
        test_parse_multiple_sprint_descriptors,
        test_parse_historical_sprint_id_from_changelog,
        test_sprint_scope_accepts_active_and_closed_2026_sprints,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\nAll {len(tests)} tests passed.")
