import unittest

from okr.domain import (
    build_monthly_metrics,
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


if __name__ == "__main__":
    unittest.main()
