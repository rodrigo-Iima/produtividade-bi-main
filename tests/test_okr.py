import unittest

from okr.domain import (
    build_monthly_metrics,
    build_ticket_clockify_table,
    extract_issue_sources,
    match_entries_to_bugs,
    parse_clockify_entries,
    parse_jira_bugs,
)


class OkrDomainTests(unittest.TestCase):
    def test_extracts_issue_keys_from_description_and_task(self):
        sources = extract_issue_sources("Correção BUG-1 e BUG-2", "BUG-1")

        self.assertEqual(
            sources,
            {
                "BUG-1": "description_and_task",
                "BUG-2": "description",
            },
        )

    def test_allocates_multi_issue_entry_without_double_counting(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "One",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 3600,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-1",
                    "description": "BUG-1 BUG-2",
                    "taskName": "Correção",
                    "timeInterval": {
                        "start": "2026-02-12T10:00:00.000Z",
                        "end": "2026-02-12T12:00:00.000Z",
                    },
                }
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )

        matches = match_entries_to_bugs(bugs, entries)

        self.assertEqual(len(matches), 2)
        self.assertEqual(sum(match.allocated_hours for match in matches), 2.0)
        self.assertEqual({match.extraction_method for match in matches}, {"description"})

    def test_monthly_metrics_use_bug_creation_month_and_report_coverage(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "One",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-20T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-1",
                    "description": "BUG-1",
                    "taskName": "",
                    "timeInterval": {
                        "start": "2026-02-12T10:00:00.000Z",
                        "end": "2026-02-12T11:00:00.000Z",
                    },
                }
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )
        metrics = build_monthly_metrics(
            bugs,
            match_entries_to_bugs(bugs, entries),
            timezone_name="America/Sao_Paulo",
        )

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].month, "2026-02")
        self.assertEqual(metrics[0].bugs_in_jira, 2)
        self.assertEqual(metrics[0].bugs_with_clockify, 1)
        self.assertEqual(metrics[0].coverage_pct, 50.0)
        self.assertEqual(metrics[0].avg_estimate_hours, 2.0)
        self.assertEqual(metrics[0].avg_actual_hours, 1.0)

    def test_ticket_table_has_one_joined_row_per_mapped_bug(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "One",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 3600,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-1",
                    "description": "BUG-1 BUG-2",
                    "taskName": "Correção",
                    "timeInterval": {
                        "start": "2026-02-12T10:00:00.000Z",
                        "end": "2026-02-12T12:00:00.000Z",
                    },
                }
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )

        rows = build_ticket_clockify_table(
            bugs,
            match_entries_to_bugs(bugs, entries),
        )

        self.assertEqual([row.issue_key for row in rows], ["BUG-2", "BUG-1"])
        self.assertEqual(rows[0].clockify_actual_hours, 1.0)
        self.assertEqual(rows[0].clockify_entry_count, 1)
        self.assertIsNone(rows[0].jira_logged_hours)
        self.assertEqual(rows[0].spent_hours, 1.0)
        self.assertEqual(rows[0].spent_source, "clockify")
        self.assertEqual(rows[0].variation_hours, 0.0)

    def test_uses_the_larger_jira_or_clockify_time_as_spent(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Jira is larger",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                        "timespent": 10800,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Clockify is larger",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 3600,
                        "timespent": 3600,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-1",
                    "description": "BUG-1",
                    "taskName": "",
                    "timeInterval": {
                        "start": "2026-02-12T10:00:00.000Z",
                        "end": "2026-02-12T11:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-2",
                    "description": "BUG-2",
                    "taskName": "",
                    "timeInterval": {
                        "start": "2026-02-12T11:00:00.000Z",
                        "end": "2026-02-12T13:00:00.000Z",
                    },
                },
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )

        rows = build_ticket_clockify_table(
            bugs,
            match_entries_to_bugs(bugs, entries),
        )

        by_key = {row.issue_key: row for row in rows}
        self.assertEqual(by_key["BUG-1"].jira_logged_hours, 3.0)
        self.assertEqual(by_key["BUG-1"].spent_hours, 3.0)
        self.assertEqual(by_key["BUG-1"].spent_source, "jira")
        self.assertEqual(by_key["BUG-1"].variation_hours, 1.0)
        self.assertEqual(by_key["BUG-2"].jira_logged_hours, 1.0)
        self.assertEqual(by_key["BUG-2"].spent_hours, 2.0)
        self.assertEqual(by_key["BUG-2"].spent_source, "clockify")
        self.assertEqual(by_key["BUG-2"].variation_hours, 1.0)

    def test_missing_numeric_fields_do_not_contaminate_monthly_averages(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Has estimate",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": 7200,
                        "timespent": None,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Empty numeric fields",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "timeoriginalestimate": "",
                        "timespent": "",
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-1",
                    "description": "BUG-1",
                    "taskName": "",
                    "timeInterval": {
                        "start": "2026-02-12T10:00:00.000Z",
                        "end": "2026-02-12T11:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-2",
                    "description": "BUG-2",
                    "taskName": "",
                    "timeInterval": {
                        "start": "2026-02-12T11:00:00.000Z",
                        "end": "2026-02-12T13:00:00.000Z",
                    },
                },
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )
        matches = match_entries_to_bugs(bugs, entries)

        metrics = build_monthly_metrics(
            bugs,
            matches,
            timezone_name="America/Sao_Paulo",
        )

        self.assertEqual(metrics[0].avg_estimate_hours, 2.0)
        self.assertEqual(metrics[0].avg_actual_hours, 1.5)
        self.assertEqual(metrics[0].avg_delta_hours, -1.0)
        self.assertEqual(metrics[0].actual_to_estimate_ratio, 0.5)

        rows = build_ticket_clockify_table(bugs, matches)
        empty_row = next(row for row in rows if row.issue_key == "BUG-2")
        self.assertIsNone(empty_row.estimate_hours)
        self.assertIsNone(empty_row.jira_logged_hours)
        self.assertIsNone(empty_row.variation_hours)


if __name__ == "__main__":
    unittest.main()
