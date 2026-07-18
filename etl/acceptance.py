"""Phase 5 validation and acceptance checks for the loaded analytical model."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from database.connection import SessionLocal
from etl.quality import DataQualityError, validate_loaded_data
from queries import hours_by_sprint, ticket_metrics, total_hours


ACCEPTANCE_VERSION = 1
OUTPUT_DIR = Path("validation")


def run_acceptance() -> dict[str, Any]:
    """Run the reproducible Phase 5 acceptance suite without changing data."""
    started_at = datetime.now(timezone.utc)
    profile = _profile()
    checks: list[dict[str, Any]] = []

    _add_check(
        checks,
        "schema_version",
        "Schema operacional da fase 4 aplicado",
        profile["schema_version"],
        ">= 4",
        profile["schema_version"] >= 4,
        "critical",
    )
    _add_check(
        checks,
        "view_version",
        "Camada de views da fase 3 aplicada",
        profile["view_version"],
        ">= 3",
        profile["view_version"] >= 3,
        "high",
    )

    for table_name, count in profile["row_counts"].items():
        required = table_name in {"dim_sprint", "dim_ticket_jira", "fato_clockify_entry"}
        _add_check(
            checks,
            f"rows_{table_name}",
            f"Tabela {table_name} carregada" if required else f"Tabela {table_name} perfilada",
            count,
            "> 0" if required else ">= 0",
            count > 0 if required else True,
            "high" if required else "info",
        )

    try:
        quality = validate_loaded_data()
        quality_checks = quality["checks"]
    except DataQualityError as error:
        quality_checks = error.checks
    for name, value in quality_checks.items():
        _add_check(
            checks,
            name,
            f"Quality gate: {name}",
            value,
            "0",
            value == 0,
            "critical",
        )

    _add_check(
        checks,
        "clockify_entry_view_grain",
        "View de lançamento mantém uma linha por entrada",
        profile["view_counts"]["vw_clockify_entry_detail"],
        profile["row_counts"]["fato_clockify_entry"],
        profile["view_counts"]["vw_clockify_entry_detail"]
        == profile["row_counts"]["fato_clockify_entry"],
        "critical",
    )
    _add_check(
        checks,
        "clockify_tag_view_grain",
        "View de tags mantém uma linha por entrada × tag",
        profile["view_counts"]["vw_clockify_entry_tag_detail"],
        profile["row_counts"]["bridge_clockify_entry_tag"],
        profile["view_counts"]["vw_clockify_entry_tag_detail"]
        == profile["row_counts"]["bridge_clockify_entry_tag"],
        "critical",
    )
    _add_check(
        checks,
        "clockify_sprint_view_grain",
        "View de sprint mantém uma linha por entrada × atribuição",
        profile["view_counts"]["vw_clockify_entry_sprint_detail"],
        profile["row_counts"]["bridge_clockify_entry_sprint"],
        profile["view_counts"]["vw_clockify_entry_sprint_detail"]
        == profile["row_counts"]["bridge_clockify_entry_sprint"],
        "critical",
    )
    _add_check(
        checks,
        "jira_view_grain",
        "View Jira mantém uma linha por ticket × sprint",
        profile["view_counts"]["vw_jira_ticket_sprint_detail"],
        profile["row_counts"]["fato_jira_ticket_sprint"],
        profile["view_counts"]["vw_jira_ticket_sprint_detail"]
        == profile["row_counts"]["fato_jira_ticket_sprint"],
        "critical",
    )

    metrics = _metric_reconciliation(profile)
    _add_check(
        checks,
        "total_hours_reconciliation",
        "Total de horas da função coincide com a soma direta da fato",
        metrics["metric_total_hours"],
        metrics["fact_total_hours"],
        abs(metrics["metric_total_hours"] - metrics["fact_total_hours"]) < 0.000001,
        "critical",
    )
    _add_check(
        checks,
        "squad_hours_reconciliation",
        "Horas por squad recompõem o total sem duplicação",
        metrics["squad_total_hours"],
        metrics["fact_total_hours"],
        abs(metrics["squad_total_hours"] - metrics["fact_total_hours"]) < 0.000001,
        "high",
    )
    _add_check(
        checks,
        "sprint_hours_bound",
        "Horas atribuídas a sprint não superam o total de lançamentos",
        metrics["assigned_sprint_hours"],
        f"<= {metrics['fact_total_hours']}",
        metrics["assigned_sprint_hours"] <= metrics["fact_total_hours"] + 0.000001,
        "high",
    )

    _add_check(
        checks,
        "historical_sprint_coverage",
        "Todo relacionamento processado no changelog existe na fato histórica",
        profile["historical_changelog_relations_missing"],
        "0",
        profile["historical_changelog_relations_missing"] == 0,
        "high",
    )
    _add_check(
        checks,
        "changelog_failures",
        "Nenhum ticket permaneceu com falha no changelog",
        profile["failed_changelog_rows"],
        "0",
        profile["failed_changelog_rows"] == 0,
        "high",
    )
    _add_check(
        checks,
        "planning_nulls",
        "Relações ticket × sprint possuem resultado de planejamento",
        profile["planning_nulls"],
        "0",
        profile["planning_nulls"] == 0,
        "high",
    )
    _add_check(
        checks,
        "unmapped_statuses",
        "Status Jira estão classificados na dimensão de status",
        profile["unmapped_statuses"],
        "0",
        profile["unmapped_statuses"] == 0,
        "medium",
        warning=profile["unmapped_statuses"] > 0,
    )
    _add_check(
        checks,
        "entries_without_tags",
        "Lançamentos sem tag são identificados para aceite funcional",
        profile["entries_without_tags"],
        "informativo",
        True,
        "medium",
        warning=profile["entries_without_tags"] > 0,
    )

    ticket = ticket_metrics()
    _add_check(
        checks,
        "ticket_efficiency_range",
        "Eficiência da sprint está entre 0% e 100%",
        ticket["eficiencia_sprint"],
        "0 <= valor <= 1",
        ticket["eficiencia_sprint"] is None
        or 0 <= ticket["eficiencia_sprint"] <= 1,
        "high",
    )

    failed = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    status = "not_accepted" if failed else (
        "accepted_with_warnings" if warnings else "accepted"
    )
    finished_at = datetime.now(timezone.utc)

    return {
        "acceptance_version": ACCEPTANCE_VERSION,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "profile": profile,
        "metrics": {**metrics, "ticket_metrics": ticket},
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(check["status"] == "pass" for check in checks),
            "warnings": len(warnings),
            "failed": len(failed),
        },
    }


def write_acceptance_report(output_dir: Path = OUTPUT_DIR) -> tuple[Path, Path, dict[str, Any]]:
    """Write machine-readable JSON and concise Markdown acceptance evidence."""
    report = run_acceptance()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "acceptance_report.json"
    markdown_path = output_dir / "acceptance_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_to_markdown(report), encoding="utf-8")
    return json_path, markdown_path, report


def _profile() -> dict[str, Any]:
    tables = (
        "dim_sprint",
        "dim_ticket_jira",
        "fato_clockify_entry",
        "bridge_clockify_entry_tag",
        "bridge_clockify_entry_issue",
        "bridge_clockify_entry_sprint",
        "fato_jira_ticket_sprint",
        "jira_sprint_changelog",
    )
    views = (
        "vw_clockify_entry_detail",
        "vw_clockify_entry_tag_detail",
        "vw_clockify_entry_sprint_detail",
        "vw_jira_ticket_sprint_detail",
    )
    session = SessionLocal()
    try:
        row_counts = {
            name: int(session.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
            for name in tables
        }
        view_counts = {
            name: int(session.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
            for name in views
        }
        schema_version = int(
            session.execute(text("SELECT COALESCE(MAX(version), 0) FROM etl_schema_version")).scalar_one()
        )
        view_version = int(
            session.execute(text("SELECT COALESCE(MAX(version), 0) FROM etl_view_version")).scalar_one()
        )
        result = {
            "schema_version": schema_version,
            "view_version": view_version,
            "row_counts": row_counts,
            "view_counts": view_counts,
            "clockify_date_range": _date_range(session, "fato_clockify_entry", "entry_date"),
            "jira_updated_range": _date_range(session, "dim_ticket_jira", "updated_at"),
            "sprint_date_range": _date_range(session, "dim_sprint", "sprint_start"),
            "failed_changelog_rows": int(session.execute(text(
                "SELECT COUNT(*) FROM jira_sprint_changelog WHERE processing_status = 'failed'"
            )).scalar_one()),
            "planning_nulls": int(session.execute(text(
                """
                SELECT COUNT(*) FROM fato_jira_ticket_sprint
                WHERE sprint_entrada_at IS NULL OR planejado_no_inicio IS NULL
                """
            )).scalar_one()),
            "unmapped_statuses": int(session.execute(text(
                """
                SELECT COUNT(DISTINCT t.status_original)
                FROM dim_ticket_jira t
                LEFT JOIN dim_status s ON s.status_original = t.status_original
                WHERE s.status_original IS NULL
                """
            )).scalar_one()),
            "entries_without_tags": int(session.execute(text(
                """
                SELECT COUNT(*) FROM fato_clockify_entry e
                LEFT JOIN bridge_clockify_entry_tag b ON b.entry_id = e.entry_id
                WHERE b.entry_id IS NULL
                """
            )).scalar_one()),
            "entries_without_sprint_assignment": int(session.execute(text(
                """
                SELECT COUNT(*) FROM fato_clockify_entry e
                LEFT JOIN bridge_clockify_entry_sprint b ON b.entry_id = e.entry_id
                WHERE b.entry_id IS NULL
                """
            )).scalar_one()),
            "ambiguous_sprint_links": int(session.execute(text(
                """
                SELECT COUNT(*) FROM bridge_clockify_entry_sprint
                WHERE assignment_status = 'ambiguo'
                """
            )).scalar_one()),
            "historical_changelog_relations_missing": int(session.execute(text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT issue_key, sprint_id
                    FROM jira_sprint_changelog
                    WHERE processing_status = 'processed' AND sprint_id IS NOT NULL
                ) c
                LEFT JOIN fato_jira_ticket_sprint r
                  ON r.issue_key = c.issue_key AND r.sprint_id = c.sprint_id
                WHERE r.issue_key IS NULL
                """
            )).scalar_one()),
        }
    finally:
        session.close()
    return result


def _metric_reconciliation(profile: dict[str, Any]) -> dict[str, float]:
    session = SessionLocal()
    try:
        fact_total = _float(session.execute(text(
            "SELECT COALESCE(SUM(duration_seconds), 0) / 3600.0 FROM fato_clockify_entry"
        )).scalar_one())
        squad_total = _float(session.execute(text(
            """
            SELECT COALESCE(SUM(duration_hours), 0)
            FROM vw_clockify_entry_detail
            """
        )).scalar_one())
        assigned_sprint = _float(session.execute(text(
            """
            SELECT COALESCE(SUM(e.duration_seconds), 0) / 3600.0
            FROM fato_clockify_entry e
            JOIN bridge_clockify_entry_sprint b ON b.entry_id = e.entry_id
            WHERE b.assignment_status = 'atribuido'
            """
        )).scalar_one())
    finally:
        session.close()

    sprint_total = sum(row["hours"] for row in hours_by_sprint())
    return {
        "fact_total_hours": fact_total,
        "metric_total_hours": total_hours(),
        "squad_total_hours": squad_total,
        "assigned_sprint_hours": sprint_total,
    }


def _date_range(session, table: str, column: str) -> dict[str, Any]:
    result = session.execute(text(
        f"SELECT MIN({column}), MAX({column}) FROM {table}"
    )).one()
    return {"min": result[0], "max": result[1]}


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


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    profile = report["profile"]
    metrics = report["metrics"]
    lines = [
        "# Fase 5 — Relatório de validação e aceite",
        "",
        f"**Status:** `{report['status']}`  ",
        f"**Executado em:** `{report['finished_at'].isoformat()}`  ",
        f"**Checks:** {summary['passed']} aprovados, {summary['warnings']} avisos, {summary['failed']} falhas.",
        "",
        "## Resumo técnico",
        "",
        f"O modelo possui {profile['row_counts']['fato_clockify_entry']:,} lançamentos Clockify, "
        f"{profile['row_counts']['dim_ticket_jira']:,} tickets Jira e "
        f"{profile['row_counts']['dim_sprint']:,} sprints dentro do escopo.",
        "",
        f"O total reconciliado é **{metrics['fact_total_hours']:.4f} horas**; "
        f"a função `total_hours()` retornou **{metrics['metric_total_hours']:.4f} horas**.",
        "",
        "## Critérios de aceite",
        "",
        "| Critério | Status | Observado | Esperado | Severidade |",
        "|---|---|---:|---:|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['name']} | {check['status']} | "
            f"{_display(check['observed'])} | {_display(check['expected'])} | {check['severity']} |"
        )
    lines.extend([
        "",
        "## Evidências e limitações",
        "",
        f"- Relações changelog sem correspondência na fato histórica: "
        f"**{profile['historical_changelog_relations_missing']}**.",
        f"- Atribuições ambíguas de sprint: **{profile['ambiguous_sprint_links']}**; "
        "elas ficam excluídas por padrão das métricas agrupadas por sprint.",
        f"- Lançamentos sem tag: **{profile['entries_without_tags']}**; "
        "o total geral continua válido, mas esses lançamentos não aparecem nos agrupamentos por tag.",
        "- A validação é sobre o banco carregado; não reexecuta APIs nem altera registros.",
        "",
        "## Próximas ações",
        "",
        "1. Corrigir qualquer critério `fail` antes de liberar o dashboard para uso operacional.",
        "2. Registrar a aprovação funcional dos KPIs com amostras revisadas pelos responsáveis.",
        "3. Usar `etl_run_log` e este relatório em cada carga agendada.",
        "",
    ])
    return "\n".join(lines)


def _display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    if value is None:
        return "null"
    return str(value)


if __name__ == "__main__":
    json_path, markdown_path, report = write_acceptance_report()
    print(json_path)
    print(markdown_path)
    print(f"status={report['status']}")
