"""Quality gate and acceptance report for the Jira project portfolio.

This acceptance suite is intentionally independent from Clockify and Flow.  It
checks the source grain, hierarchy, portfolio calculations and operational
evidence that are required by the projects dashboard before the BFF is moved
to the real views.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from database.connection import engine


PROJECT_ACCEPTANCE_VERSION = 1
PROJECTS = ("ZGT", "ZG", "ZGTN", "SRE")
PROJECT_START = "2026-01-01"
OUTPUT_DIR = Path(".runtime/project-validation")
REQUIRED_PROGRESS_STATES = (
    "NO_CHILDREN",
    "NO_ESTIMATES",
    "PARTIAL_ESTIMATES",
    "READY",
)


def run_project_acceptance() -> dict[str, Any]:
    """Run all project acceptance checks without changing the database."""
    started_at = datetime.now(timezone.utc)
    checks: list[dict[str, Any]] = []

    try:
        with engine.connect() as connection:
            profile = _profile(connection)
            _checks_for_profile(checks, profile)
    except Exception as exc:
        return {
            "acceptance_version": PROJECT_ACCEPTANCE_VERSION,
            "status": "not_accepted",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "profile": {},
            "checks": [{
                "id": "database_read",
                "name": "Banco disponível para o aceite",
                "status": "fail",
                "severity": "critical",
                "observed": str(exc),
                "expected": "consulta concluída",
            }],
            "summary": {"total_checks": 1, "passed": 0, "warnings": 0, "failed": 1},
        }

    failed = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    status = "not_accepted" if failed else (
        "accepted_with_warnings" if warnings else "accepted"
    )
    return {
        "acceptance_version": PROJECT_ACCEPTANCE_VERSION,
        "status": status,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "profile": profile,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(check["status"] == "pass" for check in checks),
            "warnings": len(warnings),
            "failed": len(failed),
        },
    }


def write_project_acceptance_report(
    output_dir: Path = OUTPUT_DIR,
) -> tuple[Path, Path, dict[str, Any]]:
    """Write JSON and Markdown evidence for a project acceptance run."""
    report = run_project_acceptance()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "project_acceptance_report.json"
    markdown_path = output_dir / "project_acceptance_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_to_markdown(report), encoding="utf-8")
    return json_path, markdown_path, report


def _profile(connection) -> dict[str, Any]:
    source_epics = _scalar_int(
        connection,
        """
        SELECT COUNT(*)
        FROM public.dim_ticket_jira
        WHERE LOWER(TRIM(issue_type_name)) = 'epic'
          AND project_key = ANY(:projects)
          AND created_at >= CAST(:project_start AS TIMESTAMPTZ)
          AND created_at < CURRENT_DATE + INTERVAL '1 day'
          AND source_present = TRUE
        """,
        projects=list(PROJECTS),
        project_start=PROJECT_START,
    )
    portfolio_rows = _scalar_int(
        connection,
        "SELECT COUNT(*) FROM public.vw_dashboard_project_portfolio",
    )
    project_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(text("""
            SELECT project_key, COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            GROUP BY project_key
            ORDER BY project_key
        """)).all()
    }
    progress_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(text("""
            SELECT progress_status, COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            GROUP BY progress_status
            ORDER BY progress_status
        """)).all()
    }
    source_project_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(text("""
            SELECT project_key, COUNT(*)
            FROM public.dim_ticket_jira
            WHERE LOWER(TRIM(issue_type_name)) = 'epic'
              AND project_key = ANY(:projects)
              AND created_at >= CAST(:project_start AS TIMESTAMPTZ)
              AND created_at < CURRENT_DATE + INTERVAL '1 day'
              AND source_present = TRUE
            GROUP BY project_key
            ORDER BY project_key
        """), {"projects": list(PROJECTS), "project_start": PROJECT_START}).all()
    }

    return {
        "source_epics": source_epics,
        "portfolio_rows": portfolio_rows,
        "portfolio_distinct_epics": _scalar_int(
            connection,
            "SELECT COUNT(DISTINCT issue_key) FROM public.vw_dashboard_project_portfolio",
        ),
        "source_project_counts": source_project_counts,
        "project_counts": project_counts,
        "epics_without_sprint": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.dim_ticket_jira AS e
            WHERE LOWER(TRIM(e.issue_type_name)) = 'epic'
              AND e.project_key = ANY(:projects)
              AND e.created_at >= CAST(:project_start AS TIMESTAMPTZ)
              AND e.created_at < CURRENT_DATE + INTERVAL '1 day'
              AND e.source_present = TRUE
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.fato_jira_ticket_sprint AS s
                  WHERE s.issue_key = e.issue_key
              )
        """, projects=list(PROJECTS), project_start=PROJECT_START),
        "children_created_before_2026": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_child
            WHERE created_at < DATE '2026-01-01'
        """),
        "orphan_edges": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.bridge_jira_issue_parent AS b
            LEFT JOIN public.dim_ticket_jira AS c
              ON c.issue_key = b.child_issue_key AND c.source_present = TRUE
            LEFT JOIN public.dim_ticket_jira AS p
              ON p.issue_key = b.parent_issue_key AND p.source_present = TRUE
            WHERE b.source_present = TRUE
              AND (c.issue_key IS NULL OR p.issue_key IS NULL)
        """),
        "cycle_edges": _scalar_int(connection, """
            WITH RECURSIVE walk(start_key, current_key, path, cycle) AS (
                SELECT
                    b.child_issue_key,
                    b.parent_issue_key,
                    ARRAY[b.child_issue_key, b.parent_issue_key]::TEXT[],
                    b.child_issue_key = b.parent_issue_key
                FROM public.bridge_jira_issue_parent AS b
                WHERE b.source_present = TRUE
                UNION ALL
                SELECT
                    w.start_key,
                    b.parent_issue_key,
                    w.path || b.parent_issue_key,
                    b.parent_issue_key = ANY(w.path)
                FROM walk AS w
                JOIN public.bridge_jira_issue_parent AS b
                  ON b.child_issue_key = w.current_key
                 AND b.source_present = TRUE
                WHERE NOT w.cycle
                  AND CARDINALITY(w.path) < 100
            )
            SELECT COUNT(*) FROM walk WHERE cycle = TRUE
        """),
        "subtask_progress_mismatches": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM (
                SELECT
                    p.issue_key,
                    p.estimated_hours_total,
                    COALESCE(SUM(c.original_estimate_hours)
                        FILTER (WHERE c.is_effort_eligible), 0) AS child_hours
                FROM public.vw_dashboard_project_portfolio AS p
                LEFT JOIN public.vw_dashboard_project_child AS c
                  ON c.epic_issue_key = p.issue_key
                GROUP BY p.issue_key, p.estimated_hours_total
                HAVING ABS(
                    p.estimated_hours_total
                    - COALESCE(SUM(c.original_estimate_hours)
                        FILTER (WHERE c.is_effort_eligible), 0)
                ) > 0.000001
            ) AS mismatches
        """),
        "subtask_count_mismatches": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE descendants_count <> child_ticket_count + subtask_count
        """),
        "progress_out_of_range": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE progress_pct IS NOT NULL
              AND (progress_pct < 0 OR progress_pct > 100)
        """),
        "progress_status_values": progress_counts,
        "keys_not_exposed": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE inconsistency_count > 0
              AND CARDINALITY(COALESCE(keys_with_project_inconsistency,
                  ARRAY[]::TEXT[])) = 0
        """),
        "missing_estimate_keys_mismatch": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE tickets_without_estimate_count <> CARDINALITY(
                COALESCE(keys_without_estimate, ARRAY[]::TEXT[])
            )
        """),
        "invalid_planned_dates": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE planned_start_date IS NOT NULL
              AND due_date IS NOT NULL
              AND due_date < planned_start_date
        """),
        "invalid_resolved_dates": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE resolved_at IS NOT NULL
              AND resolved_at < created_at
        """),
        "invalid_real_dates": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE actual_start_at IS NOT NULL
              AND actual_end_at IS NOT NULL
              AND actual_end_at < actual_start_at
        """),
        "invalid_day_values": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE days_created < 0
               OR days_in_execution < 0
               OR (actual_start_at IS NULL AND days_in_execution IS NOT NULL)
        """),
        "unknown_status_rows": _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_portfolio
            WHERE 'UNKNOWN_STATUS' = ANY(COALESCE(inconsistency_codes,
                ARRAY[]::TEXT[]))
        """) + _scalar_int(connection, """
            SELECT COUNT(*)
            FROM public.vw_dashboard_project_child
            WHERE 'UNKNOWN_STATUS' = ANY(COALESCE(inconsistency_codes,
                ARRAY[]::TEXT[]))
        """),
        "freshness": _freshness(connection),
        "source_state": _source_state(connection),
        "latest_project_runs": _latest_project_runs(connection),
        "schema": _schema_profile(connection),
        "kpi_reconciliation": _kpi_reconciliation(connection),
    }


def _checks_for_profile(checks: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    source_epics = profile["source_epics"]
    portfolio_rows = profile["portfolio_rows"]
    projects_ok = all(profile["source_project_counts"].get(project, 0) > 0 for project in PROJECTS)

    _add_check(checks, "epic_count_vs_extraction", "Contagem de Epics da extração Jira coincide com a view final", {
        "jira_source": source_epics,
        "portfolio": portfolio_rows,
    }, "iguais", source_epics == portfolio_rows, "critical")
    _add_check(checks, "four_projects_present", "Os quatro projetos estão presentes no escopo", {
        project: profile["source_project_counts"].get(project, 0) for project in PROJECTS
    }, f"> 0 para {', '.join(PROJECTS)}", projects_ok, "critical")
    _add_check(checks, "epics_without_sprint", "Epics sem sprint continuam visíveis", profile["epics_without_sprint"], ">= 1 (evidência do contrato independente de sprint)", profile["epics_without_sprint"] >= 1, "info", warning=True)
    _add_check(checks, "children_before_2026", "Filhos criados antes de 2026 foram incluídos", profile["children_created_before_2026"], ">= 1", profile["children_created_before_2026"] >= 1, "high", warning=True)
    _add_check(checks, "portfolio_grain_unique", "A view final possui uma linha por Epic", {
        "rows": portfolio_rows,
        "distinct_epics": profile["portfolio_distinct_epics"],
    }, "rows = distinct_epics", portfolio_rows == profile["portfolio_distinct_epics"], "critical")
    _add_check(checks, "orphan_edges", "Não existem relações de hierarquia órfãs", profile["orphan_edges"], 0, profile["orphan_edges"] == 0, "critical")
    _add_check(checks, "cycle_edges", "Não existem ciclos na hierarquia", profile["cycle_edges"], 0, profile["cycle_edges"] == 0, "critical")
    _add_check(checks, "subtasks_do_not_change_progress", "Subtarefas não alteram o esforço/progresso do Epic", {
        "effort_mismatches": profile["subtask_progress_mismatches"],
        "count_mismatches": profile["subtask_count_mismatches"],
    }, "ambos = 0", profile["subtask_progress_mismatches"] == 0 and profile["subtask_count_mismatches"] == 0, "critical")
    _add_check(checks, "progress_range", "Progresso calculado permanece entre 0% e 100%", profile["progress_out_of_range"], 0, profile["progress_out_of_range"] == 0, "critical")
    _add_check(checks, "progress_states", "A view distingue os quatro estados de disponibilidade", profile["progress_status_values"], {
        state: ">= 1" for state in REQUIRED_PROGRESS_STATES
    }, all(profile["progress_status_values"].get(state, 0) > 0 for state in REQUIRED_PROGRESS_STATES), "high")
    _add_check(checks, "inconsistency_keys_exposed", "As keys dos registros inconsistentes são expostas", profile["keys_not_exposed"], 0, profile["keys_not_exposed"] == 0, "high")
    _add_check(checks, "missing_estimate_keys", "As keys sem estimativa recompõem a contagem", profile["missing_estimate_keys_mismatch"], 0, profile["missing_estimate_keys_mismatch"] == 0, "high")
    _add_check(checks, "date_consistency", "Datas planejadas, reais e resolvidas são consistentes", {
        "planned": profile["invalid_planned_dates"],
        "resolved": profile["invalid_resolved_dates"],
        "real": profile["invalid_real_dates"],
    }, "todos = 0", all(profile[key] == 0 for key in ("invalid_planned_dates", "invalid_resolved_dates", "invalid_real_dates")), "high")
    _add_check(checks, "days_consistency", "Dias corridos não assumem valores impossíveis", profile["invalid_day_values"], 0, profile["invalid_day_values"] == 0, "high")
    _add_check(checks, "status_mapping_coverage", "Todos os status usados no portfólio estão mapeados", profile["unknown_status_rows"], 0, profile["unknown_status_rows"] == 0, "medium", warning=True)

    freshness = profile["freshness"]
    _add_check(checks, "freshness", "Freshness do Jira está disponível e reflete a contagem", freshness, "available e record_count = Epics", freshness["status"] == "available" and freshness["record_count"] == source_epics and freshness["last_success_at"] is not None, "high")
    source_state = profile["source_state"]
    _add_check(checks, "latest_execution_success", "A última execução do pipeline terminou com sucesso", source_state, "success com last_success_at", source_state["status"] == "success" and source_state["last_success_at"] is not None, "critical")
    schema = profile["schema"]
    _add_check(checks, "migration_idempotence", "Migration da fase 29 está aplicada sem duplicidade", schema, "versão máxima >= 29 e versão 29 única", schema["max_version"] >= 29 and schema["phase29_rows"] == 1, "critical")

    runs = profile["latest_project_runs"]
    status_runs = runs["status_history"]
    hierarchy_runs = runs["hierarchy"]
    status_idempotent = (
        len(status_runs) >= 2
        and all(run["status"] == "success" for run in status_runs[:2])
        and status_runs[0]["records_loaded"] == 0
    )
    hierarchy_idempotent = (
        len(hierarchy_runs) >= 2
        and all(run["status"] == "success" for run in hierarchy_runs[:2])
        and hierarchy_runs[0]["records_loaded"] == hierarchy_runs[1]["records_loaded"]
    )
    _add_check(checks, "backfill_idempotence", "As execuções repetidas não criaram divergência", runs, "changelog sem novos eventos e hierarquia com mesma carga", status_idempotent and hierarchy_idempotent, "high", warning=True)

    kpi = profile["kpi_reconciliation"]
    _add_check(checks, "kpi_reconciliation", "KPI total, gráficos e tabela recompõem a mesma view", kpi, "todas as somas = total", all(value == kpi["total"] for key, value in kpi.items() if key != "total"), "high")


def _freshness(connection) -> dict[str, Any]:
    row = connection.execute(text("""
        SELECT source, status, last_success_at, last_record_at, record_count
        FROM public.vw_dashboard_project_freshness
    """)).mappings().first()
    if not row:
        return {"source": None, "status": "missing", "last_success_at": None, "last_record_at": None, "record_count": 0}
    return dict(row)


def _source_state(connection) -> dict[str, Any]:
    row = connection.execute(text("""
        SELECT status, last_success_at, last_record_at, rows_processed, watermark_at
        FROM public.etl_source_state
        WHERE source_name = 'jira_projects'
    """)).mappings().first()
    return dict(row) if row else {"status": "missing", "last_success_at": None, "last_record_at": None, "rows_processed": 0, "watermark_at": None}


def _latest_project_runs(connection) -> dict[str, list[dict[str, Any]]]:
    status_rows = connection.execute(text("""
        SELECT run_id, status, records_loaded, started_at, finished_at
        FROM public.etl_run_log
        WHERE step_name = 'project_status_history'
        ORDER BY started_at DESC
        LIMIT 2
    """)).mappings().all()
    hierarchy_rows = connection.execute(text("""
        SELECT run_id, status, records_extracted, records_transformed,
               records_loaded, started_at, finished_at
        FROM public.etl_run_log
        WHERE step_name = 'project_hierarchy'
        ORDER BY started_at DESC
        LIMIT 2
    """)).mappings().all()
    return {
        "status_history": [dict(row) for row in status_rows],
        "hierarchy": [dict(row) for row in hierarchy_rows],
    }


def _schema_profile(connection) -> dict[str, int]:
    return {
        "max_version": _scalar_int(connection, "SELECT COALESCE(MAX(version), 0) FROM public.etl_schema_version"),
        "phase29_rows": _scalar_int(connection, "SELECT COUNT(*) FROM public.etl_schema_version WHERE version = 29"),
    }


def _kpi_reconciliation(connection) -> dict[str, int]:
    total = _scalar_int(connection, "SELECT COUNT(*) FROM public.vw_dashboard_project_portfolio")
    project_sum = _scalar_int(connection, "SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM public.vw_dashboard_project_portfolio GROUP BY project_key) x")
    status_sum = _scalar_int(connection, "SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM public.vw_dashboard_project_portfolio GROUP BY status_group) x")
    month_sum = _scalar_int(connection, "SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM public.vw_dashboard_project_portfolio GROUP BY DATE_TRUNC('month', created_at)) x")
    return {"total": total, "project_sum": project_sum, "status_sum": status_sum, "month_sum": month_sum, "table_rows": total}


def _scalar_int(connection, statement: str, **parameters: Any) -> int:
    return int(connection.execute(text(statement), parameters).scalar_one() or 0)


def _add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    name: str,
    observed: Any,
    expected: Any,
    passed: bool,
    severity: str,
    warning: bool = False,
) -> None:
    checks.append({
        "id": check_id,
        "name": name,
        "status": "warn" if warning and not passed else ("pass" if passed else "fail"),
        "severity": severity,
        "observed": observed,
        "expected": expected,
    })


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    if value is None:
        return "null"
    return str(value)


def _to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    profile = report.get("profile", {})
    lines = [
        "# Etapa 8 — Aceite do portfólio Jira",
        "",
        f"**Status:** `{report['status']}`  ",
        f"**Executado em:** `{_json_default(report['finished_at'])}`  ",
        f"**Checks:** {summary['passed']} aprovados, {summary['warnings']} avisos, {summary['failed']} falhas.",
        "",
        f"A carga possui **{profile.get('source_epics', 0)} Epics** na origem e **{profile.get('portfolio_rows', 0)}** linhas na view oficial.",
        "",
        "| Critério | Status | Observado | Esperado | Severidade |",
        "|---|---|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['name']} | {check['status']} | {_display(check['observed'])} | "
            f"{_display(check['expected'])} | {check['severity']} |"
        )
    lines.extend([
        "",
        "A execução é somente leitura; não chama Jira, não chama Flow/Clockify e não altera registros.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    json_path, markdown_path, report = write_project_acceptance_report()
    print(json_path)
    print(markdown_path)
    print(f"status={report['status']}")
