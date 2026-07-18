"""Unit tests for Phase 4 transformations that do not require PostgreSQL."""

from datetime import datetime, timezone

from etl.clockify import ClockifyService


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


if __name__ == "__main__":
    tests = [
        test_clockify_report_rows_are_deduplicated_by_entry_id,
        test_clockify_transform_deduplicates_tags_before_composite_load,
        test_clockify_interval_overlap_excludes_entry_after_sprint_end,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\nAll {len(tests)} Phase 4 tests passed.")
