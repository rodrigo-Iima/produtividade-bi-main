"""Validation and reconciliation checks for the Jira project portfolio.

The project pipeline deliberately depends only on Jira-backed tables and
views.  Clockify and Flow are not consulted here, so a project backfill can be
run independently while those sources are unavailable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from database.connection import engine


PROJECTS = ("ZGT", "ZG", "ZGTN", "SRE")


def validate_project_data() -> dict[str, Any]:
    """Run structural and business-rule checks on the portfolio views."""
    try:
        with engine.connect() as connection:
            source_epics = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.dim_ticket_jira
                WHERE LOWER(TRIM(issue_type_name)) = 'epic'
                  AND project_key = ANY(:projects)
                  AND created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
                  AND created_at < CURRENT_DATE + INTERVAL '1 day'
                  AND source_present = TRUE
                """,
                projects=list(PROJECTS),
            )
            portfolio_rows = _scalar(
                connection,
                "SELECT COUNT(*) FROM public.vw_dashboard_project_portfolio",
            )
            distinct_portfolio_epics = _scalar(
                connection,
                """
                SELECT COUNT(DISTINCT issue_key)
                FROM public.vw_dashboard_project_portfolio
                """,
            )
            progress_out_of_range = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.vw_dashboard_project_portfolio
                WHERE progress_pct IS NOT NULL
                  AND (progress_pct < 0 OR progress_pct > 100)
                """,
            )
            invalid_real_dates = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.vw_dashboard_project_portfolio
                WHERE actual_start_at IS NOT NULL
                  AND actual_end_at IS NOT NULL
                  AND actual_end_at < actual_start_at
                """,
            )
            unknown_status = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.vw_dashboard_project_portfolio
                WHERE 'UNKNOWN_STATUS' = ANY(COALESCE(inconsistency_codes, ARRAY[]::TEXT[]))
                """,
            )
            orphan_edges = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.bridge_jira_issue_parent AS b
                JOIN public.dim_ticket_jira AS p
                  ON p.issue_key = b.parent_issue_key
                 AND LOWER(TRIM(p.issue_type_name)) = 'epic'
                 AND p.project_key = ANY(:projects)
                 AND p.source_present = TRUE
                LEFT JOIN public.dim_ticket_jira AS c
                  ON c.issue_key = b.child_issue_key
                 AND c.source_present = TRUE
                WHERE b.source_present = TRUE
                  AND c.issue_key IS NULL
                """,
                projects=list(PROJECTS),
            )
            cycle_edges = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.bridge_jira_issue_parent AS a
                JOIN public.bridge_jira_issue_parent AS b
                  ON b.child_issue_key = a.parent_issue_key
                 AND b.parent_issue_key = a.child_issue_key
                WHERE a.source_present = TRUE
                  AND b.source_present = TRUE
                """,
            )
            orphan_transitions = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.fato_jira_status_transicao AS tr
                LEFT JOIN public.dim_ticket_jira AS t
                  ON t.issue_key = tr.issue_key
                WHERE tr.source_present = TRUE
                  AND t.issue_key IS NULL
                """,
            )
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "checks": {},
        }

    checks = {
        "source_epics": source_epics,
        "portfolio_rows": portfolio_rows,
        "portfolio_distinct_epics": distinct_portfolio_epics,
        "portfolio_grain_unique": portfolio_rows == distinct_portfolio_epics,
        "portfolio_matches_source": source_epics == portfolio_rows,
        "progress_out_of_range": progress_out_of_range,
        "invalid_real_dates": invalid_real_dates,
        "unknown_status": unknown_status,
        "orphan_edges": orphan_edges,
        "cycle_edges": cycle_edges,
        "orphan_transitions": orphan_transitions,
    }
    errors = {
        name: value
        for name, value in checks.items()
        if name in {
            "portfolio_grain_unique",
            "portfolio_matches_source",
        }
        and value is False
    }
    errors.update({
        name: value
        for name, value in checks.items()
        if name in {
            "progress_out_of_range",
            "invalid_real_dates",
            "orphan_edges",
            "cycle_edges",
            "orphan_transitions",
        }
        and value != 0
    })
    warnings = {
        "unknown_status": unknown_status,
    }
    if source_epics == 0:
        status = "not_ready"
    elif errors:
        status = "failed"
    else:
        status = "passed"
    return {
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def reconcile_project_data() -> dict[str, Any]:
    """Reconcile source dimensions, hierarchy edges and portfolio views."""
    try:
        with engine.connect() as connection:
            source_epics = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.dim_ticket_jira
                WHERE LOWER(TRIM(issue_type_name)) = 'epic'
                  AND project_key = ANY(:projects)
                  AND created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
                  AND created_at < CURRENT_DATE + INTERVAL '1 day'
                  AND source_present = TRUE
                """,
                projects=list(PROJECTS),
            )
            portfolio_rows = _scalar(
                connection,
                "SELECT COUNT(*) FROM public.vw_dashboard_project_portfolio",
            )
            missing_epics = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.dim_ticket_jira AS e
                LEFT JOIN public.vw_dashboard_project_portfolio AS p
                  ON p.issue_key = e.issue_key
                WHERE LOWER(TRIM(e.issue_type_name)) = 'epic'
                  AND e.project_key = ANY(:projects)
                  AND e.created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
                  AND e.created_at < CURRENT_DATE + INTERVAL '1 day'
                  AND e.source_present = TRUE
                  AND p.issue_key IS NULL
                """,
                projects=list(PROJECTS),
            )
            source_absent_epics = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.dim_ticket_jira
                WHERE LOWER(TRIM(issue_type_name)) = 'epic'
                  AND project_key = ANY(:projects)
                  AND created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
                  AND source_present = FALSE
                """,
                projects=list(PROJECTS),
            )
            orphan_edges = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.bridge_jira_issue_parent AS b
                LEFT JOIN public.dim_ticket_jira AS c
                  ON c.issue_key = b.child_issue_key
                LEFT JOIN public.dim_ticket_jira AS p
                  ON p.issue_key = b.parent_issue_key
                WHERE b.source_present = TRUE
                  AND (c.issue_key IS NULL OR p.issue_key IS NULL)
                """,
            )
            orphan_transitions = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.fato_jira_status_transicao AS tr
                LEFT JOIN public.dim_ticket_jira AS t
                  ON t.issue_key = tr.issue_key
                WHERE tr.source_present = TRUE
                  AND t.issue_key IS NULL
                """,
            )
            edge_rows = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.bridge_jira_issue_parent
                WHERE source_present = TRUE
                """,
            )
            transition_rows = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM public.fato_jira_status_transicao
                WHERE source_present = TRUE
                """,
            )
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "checks": {},
        }

    checks = {
        "source_epics": source_epics,
        "portfolio_rows": portfolio_rows,
        "epic_count_delta": source_epics - portfolio_rows,
        "missing_epics": missing_epics,
        "source_absent_epics": source_absent_epics,
        "active_hierarchy_edges": edge_rows,
        "orphan_edges": orphan_edges,
        "active_status_transitions": transition_rows,
        "orphan_transitions": orphan_transitions,
    }
    divergence = {
        name: value
        for name, value in checks.items()
        if name in {
            "epic_count_delta",
            "missing_epics",
            "orphan_edges",
            "orphan_transitions",
        }
        and value != 0
    }
    if source_epics == 0:
        status = "not_ready"
    elif divergence:
        status = "diverged"
    else:
        status = "reconciled"
    return {
        "status": status,
        "checks": checks,
        "divergence": divergence,
    }


def _scalar(connection, statement: str, **parameters: Any) -> int:
    return int(connection.execute(text(statement), parameters).scalar_one() or 0)

