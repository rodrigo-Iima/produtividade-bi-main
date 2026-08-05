import unittest
from datetime import date

from config.settings import build_okr_adaptativa_jql, build_okr_bugs_jql
from okr.domain import (
    build_monthly_metrics,
    build_period_metrics,
    build_ticket_clockify_table,
    extract_issue_sources,
    match_entries_to_bugs,
    parse_clockify_entries,
    parse_jira_bugs,
)
from okr.pipeline import RawInputs, analyze_inputs, result_to_payload


class OkrDomainTests(unittest.TestCase):
    def test_builds_distinct_jql_scope_for_bugs_and_operadoras_adaptativas(self):
        as_of_date = date(2026, 8, 5)

        bugs_jql = build_okr_bugs_jql(as_of_date)
        adaptativa_jql = build_okr_adaptativa_jql(as_of_date)

        self.assertIn('project = ZG AND issuetype = "Bug"', bugs_jql)
        self.assertNotIn('squad[dropdown]', bugs_jql)
        self.assertIn(
            '(project = ZGT AND "squad[dropdown]" = "ZGT - Novas Operadoras")',
            adaptativa_jql,
        )
        self.assertIn(
            '(project = ZG AND "squad[dropdown]" = Operadoras)',
            adaptativa_jql,
        )
        self.assertIn('AND issuetype = "Adaptativa"', adaptativa_jql)
        self.assertIn('AND status = Done', adaptativa_jql)
        self.assertIn('AND created <= "2026-08-05"', adaptativa_jql)

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
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
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

    def test_keeps_only_entries_with_exact_dev_tag(self):
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-dev",
                    "description": "BUG-1",
                    "tags": [{"name": "Dev"}],
                    "timeInterval": {
                        "start": "2026-07-02T10:00:00.000Z",
                        "end": "2026-07-02T11:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-dev-check",
                    "description": "BUG-1",
                    "tags": [{"name": "Dev-check"}],
                    "timeInterval": {
                        "start": "2026-07-02T11:00:00.000Z",
                        "end": "2026-07-02T12:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-qa",
                    "description": "BUG-1",
                    "tags": [{"name": "QA"}],
                    "timeInterval": {
                        "start": "2026-07-02T12:00:00.000Z",
                        "end": "2026-07-02T13:00:00.000Z",
                    },
                },
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
            required_tag_name="Dev",
        )

        self.assertEqual([entry.entry_id for entry in entries], ["entry-dev"])
        self.assertEqual(entries[0].tag_names, ("Dev",))

    def test_monthly_metrics_use_bug_creation_month_and_report_coverage(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "One",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-20T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
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
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Two",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
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
        self.assertEqual(rows[0].spent_source, "clockify_dev")
        self.assertEqual(rows[0].variation_hours, 0.0)

    def test_uses_only_clockify_time_even_when_jira_is_larger(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Jira is larger",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
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
                        "status": {"name": "Concluído"},
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
        self.assertEqual(by_key["BUG-1"].spent_hours, 1.0)
        self.assertEqual(by_key["BUG-1"].spent_source, "clockify_dev")
        self.assertEqual(by_key["BUG-1"].variation_hours, -1.0)
        self.assertEqual(by_key["BUG-2"].jira_logged_hours, 1.0)
        self.assertEqual(by_key["BUG-2"].spent_hours, 2.0)
        self.assertEqual(by_key["BUG-2"].spent_source, "clockify_dev")
        self.assertEqual(by_key["BUG-2"].variation_hours, 1.0)

    def test_period_metrics_pool_tickets_and_exclude_june(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BASE-1",
                    "fields": {
                        "summary": "Baseline mapped",
                        "created": "2026-01-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "BASE-2",
                    "fields": {
                        "summary": "Baseline without Dev entry",
                        "created": "2026-05-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 21600,
                    },
                },
                {
                    "key": "JUNE-1",
                    "fields": {
                        "summary": "June excluded",
                        "created": "2026-06-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 36000,
                    },
                },
                {
                    "key": "CURR-1",
                    "fields": {
                        "summary": "Current",
                        "created": "2026-07-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 10800,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )
        entries = parse_clockify_entries(
            [
                {
                    "_id": "entry-base",
                    "description": "BASE-1",
                    "timeInterval": {
                        "start": "2026-01-11T10:00:00.000Z",
                        "end": "2026-01-11T11:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-june",
                    "description": "JUNE-1",
                    "timeInterval": {
                        "start": "2026-06-11T10:00:00.000Z",
                        "end": "2026-06-11T20:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-current",
                    "description": "CURR-1",
                    "timeInterval": {
                        "start": "2026-07-11T10:00:00.000Z",
                        "end": "2026-07-11T12:00:00.000Z",
                    },
                },
            ],
            target_year=2026,
            timezone_name="America/Sao_Paulo",
        )
        matches = match_entries_to_bugs(bugs, entries)

        periods = build_period_metrics(
            bugs,
            matches,
            target_year=2026,
            as_of_date=date(2026, 7, 24),
            timezone_name="America/Sao_Paulo",
        )
        baseline, current = periods

        self.assertEqual(baseline.bugs_in_jira, 2)
        self.assertEqual(baseline.bugs_with_clockify, 1)
        self.assertEqual(baseline.coverage_pct, 50.0)
        self.assertEqual(baseline.avg_estimate_hours, 4.0)
        self.assertEqual(baseline.avg_actual_hours, 1.0)
        self.assertEqual(baseline.avg_delta_hours, -1.0)
        self.assertEqual(current.bugs_in_jira, 1)
        self.assertEqual(current.avg_estimate_hours, 3.0)
        self.assertEqual(current.avg_actual_hours, 2.0)
        self.assertEqual(current.avg_delta_hours, -1.0)

    def test_missing_numeric_fields_do_not_contaminate_monthly_averages(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Has estimate",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
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
                        "status": {"name": "Concluído"},
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

    def test_keeps_only_completed_bug_and_adaptativa_tickets(self):
        tickets = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Concluído",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 3600,
                    },
                },
                {
                    "key": "BUG-2",
                    "fields": {
                        "summary": "Ainda em Dev",
                        "created": "2026-02-11T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Dev"},
                        "timeoriginalestimate": 3600,
                    },
                },
                {
                    "key": "ADP-1",
                    "fields": {
                        "summary": "Adaptativa concluída",
                        "created": "2026-02-12T12:00:00.000+0000",
                        "issuetype": {"name": "Adaptativa"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
                {
                    "key": "IMP-1",
                    "fields": {
                        "summary": "Outro tipo",
                        "created": "2026-02-13T12:00:00.000+0000",
                        "issuetype": {"name": "Melhoria"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )

        self.assertEqual([ticket.issue_key for ticket in tickets], ["BUG-1", "ADP-1"])
        self.assertEqual([ticket.issue_type for ticket in tickets], ["Bug", "Adaptativa"])
        self.assertTrue(all(ticket.status == "Concluído" for ticket in tickets))

    def test_serializes_independent_views_for_each_ticket_type(self):
        inputs = RawInputs(
            jql='issuetype in ("Bug", "Adaptativa") AND status = "Concluído"',
            as_of_date=date(2026, 7, 24),
            jira_issues=(
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Bug concluído",
                        "created": "2026-02-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 3600,
                    },
                },
                {
                    "key": "ADP-1",
                    "fields": {
                        "summary": "Adaptativa concluída",
                        "created": "2026-07-10T12:00:00.000+0000",
                        "issuetype": {"name": "Adaptativa"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 7200,
                    },
                },
            ),
            clockify_entries=(
                {
                    "_id": "entry-bug",
                    "description": "BUG-1",
                    "tags": [{"name": "Dev"}],
                    "timeInterval": {
                        "start": "2026-02-11T10:00:00.000Z",
                        "end": "2026-02-11T11:00:00.000Z",
                    },
                },
                {
                    "_id": "entry-adaptativa",
                    "description": "ADP-1",
                    "tags": [{"name": "Dev"}],
                    "timeInterval": {
                        "start": "2026-07-11T10:00:00.000Z",
                        "end": "2026-07-11T12:00:00.000Z",
                    },
                },
            ),
        )
        result = analyze_inputs(
            inputs,
            target_year=2026,
            timezone_name="America/Sao_Paulo",
            estimate_field="timeoriginalestimate",
        )
        payload = result_to_payload(
            result,
            jql=inputs.jql,
            target_year=2026,
            timezone_name="America/Sao_Paulo",
            estimate_field="timeoriginalestimate",
            as_of_date=inputs.as_of_date,
        )

        self.assertEqual(set(payload["views"]), {"bug", "adaptativa"})
        self.assertEqual(
            [ticket["issue_key"] for ticket in payload["views"]["bug"]["bugs"]],
            ["BUG-1"],
        )
        self.assertEqual(
            [ticket["issue_key"] for ticket in payload["views"]["adaptativa"]["bugs"]],
            ["ADP-1"],
        )
        self.assertEqual(
            payload["views"]["bug"]["tickets_with_clockify"][0]["spent_hours"],
            1.0,
        )
        self.assertEqual(
            payload["views"]["adaptativa"]["tickets_with_clockify"][0]["spent_hours"],
            2.0,
        )

    def test_zero_estimate_is_treated_as_missing(self):
        bugs = parse_jira_bugs(
            [
                {
                    "key": "BUG-1",
                    "fields": {
                        "summary": "Zero is not a usable estimate",
                        "created": "2026-07-10T12:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "status": {"name": "Concluído"},
                        "timeoriginalestimate": 0,
                    },
                }
            ],
            target_year=2026,
            estimate_field="timeoriginalestimate",
        )

        self.assertIsNone(bugs[0].estimate_hours)


if __name__ == "__main__":
    unittest.main()
