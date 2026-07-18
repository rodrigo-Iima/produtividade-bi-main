"""Build the read-only Phase 4 dashboard snapshot from PostgreSQL."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from queries import (
    clockify_kpis,
    hours_by_squad,
    hours_by_sprint,
    hours_by_tag,
    hours_by_tag_and_sprint,
    ticket_metrics,
    tickets_by_sprint,
)


ARTIFACT_PATH = ROOT / "artifact.json"


def build_artifact() -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    tags = hours_by_tag()
    tag_sprint = hours_by_tag_and_sprint()
    sprints = hours_by_sprint()
    squads = hours_by_squad()
    ticket_sprints = tickets_by_sprint()

    datasets = {
        "clockify_kpis": [clockify_kpis()],
        "jira_kpis": [ticket_metrics()],
        "hours_by_squad": squads,
        "hours_by_tag": tags,
        "hours_by_tag_top": sorted(
            tags, key=lambda row: row.get("hours", 0), reverse=True
        )[:15],
        "hours_by_sprint": sprints,
        "hours_by_tag_sprint": tag_sprint,
        "tickets_by_sprint": ticket_sprints,
    }

    sources = _sources(generated_at)
    manifest = _manifest(generated_at, sources)
    return {
        "surface": "dashboard",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": datasets,
            "accessIssues": [],
        },
        "sources": sources,
    }


def write_artifact() -> Path:
    artifact = build_artifact()
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return ARTIFACT_PATH


def _manifest(generated_at: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "surface": "dashboard",
        "title": "Gestão à vista — Produtividade",
        "description": (
            "Snapshot operacional das horas Clockify e da execução de tickets "
            "Jira nas sprints de 2026."
        ),
        "generatedAt": generated_at,
        "filters": [
            {
                "id": "sprint_filter",
                "label": "Sprint",
                "dataset": "hours_by_sprint",
                "field": "sprint_name",
                "includeAll": True,
                "targets": [
                    {"dataset": "hours_by_sprint", "field": "sprint_name"},
                    {"dataset": "hours_by_tag_sprint", "field": "sprint_name"},
                    {"dataset": "tickets_by_sprint", "field": "sprint_name"},
                ],
            },
            {
                "id": "tag_filter",
                "label": "Tag",
                "dataset": "hours_by_tag",
                "field": "tag_name",
                "includeAll": True,
                "targets": [
                    {"dataset": "hours_by_tag", "field": "tag_name"},
                    {"dataset": "hours_by_tag_sprint", "field": "tag_name"},
                ],
            },
            {
                "id": "squad_filter",
                "label": "Squad do colaborador",
                "dataset": "hours_by_squad",
                "field": "squad_name",
                "includeAll": True,
                "targets": [
                    {"dataset": "hours_by_squad", "field": "squad_name"},
                ],
            },
            {
                "id": "focus_filter",
                "label": "Foco",
                "dataset": "hours_by_tag",
                "field": "foco_flag",
                "includeAll": True,
                "targets": [
                    {"dataset": "hours_by_tag", "field": "foco_flag"},
                    {"dataset": "hours_by_tag_sprint", "field": "foco_flag"},
                ],
            },
        ],
        "cards": [
            {
                "id": "hours_total_card",
                "description": "Horas totais no grão de lançamento, sem duplicação por tag.",
                "dataset": "clockify_kpis",
                "sourceId": "clockify_kpi_source",
                "metrics": [{"label": "Horas totais", "field": "horas_total", "format": "number", "unit": "h"}],
            },
            {
                "id": "engineering_card",
                "description": "Horas em Análise, QA, Dev e Dev-Check.",
                "dataset": "clockify_kpis",
                "sourceId": "clockify_kpi_source",
                "metrics": [{"label": "Horas Engenharia", "field": "horas_engenharia", "format": "number", "unit": "h"}],
            },
            {
                "id": "dev_card",
                "description": "Horas lançadas com a tag Dev.",
                "dataset": "clockify_kpis",
                "sourceId": "clockify_kpi_source",
                "metrics": [{"label": "Horas Dev", "field": "horas_dev", "format": "number", "unit": "h"}],
            },
            {
                "id": "support_card",
                "description": "QA e Dev-Check como proporção das Horas Engenharia.",
                "dataset": "clockify_kpis",
                "sourceId": "clockify_kpi_source",
                "metrics": [{"label": "% Apoio à Entrega", "field": "percentual_apoio_entrega", "format": "percent"}],
            },
            {
                "id": "focus_card",
                "description": "Dentro do Foco dividido pelo total elegível de foco.",
                "dataset": "clockify_kpis",
                "sourceId": "clockify_kpi_source",
                "metrics": [{"label": "% Horas Foco", "field": "percentual_horas_foco", "format": "percent"}],
            },
            {
                "id": "tickets_total_card",
                "description": "Tickets relacionados às sprints dentro do escopo analítico.",
                "dataset": "jira_kpis",
                "sourceId": "jira_sprint_source",
                "metrics": [{"label": "Tickets totais", "field": "tickets_total", "format": "number"}],
            },
            {
                "id": "tickets_done_card",
                "description": "Tickets no status agrupado Concluído.",
                "dataset": "jira_kpis",
                "sourceId": "jira_sprint_source",
                "metrics": [{"label": "Tickets concluídos", "field": "tickets_concluidos", "format": "number"}],
            },
            {
                "id": "planned_card",
                "description": "Tickets que já estavam na sprint no início.",
                "dataset": "jira_kpis",
                "sourceId": "jira_sprint_source",
                "metrics": [{"label": "Planejados no início", "field": "tickets_planejados_inicio", "format": "number"}],
            },
            {
                "id": "planned_done_card",
                "description": "Tickets planejados no início que foram concluídos.",
                "dataset": "jira_kpis",
                "sourceId": "jira_sprint_source",
                "metrics": [{"label": "Planejados concluídos", "field": "tickets_planejados_concluidos", "format": "number"}],
            },
            {
                "id": "efficiency_card",
                "description": "Planejados concluídos dividido pelos planejados no início.",
                "dataset": "jira_kpis",
                "sourceId": "jira_sprint_source",
                "metrics": [{"label": "% Eficiência da Sprint", "field": "eficiencia_sprint", "format": "percent"}],
            },
        ],
        "charts": [
            {
                "id": "hours_sprint_chart",
                "title": "Horas atribuídas por sprint",
                "subtitle": "Considera atribuições de sprint com status atribuído.",
                "type": "bar",
                "dataset": "hours_by_sprint",
                "sourceId": "clockify_sprint_source",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "sprint_name", "type": "nominal", "label": "Sprint"},
                    "y": {"field": "hours", "type": "quantitative", "label": "Horas"},
                    "tooltip": [
                        {"field": "assignment_status", "type": "nominal", "label": "Atribuição"},
                        {"field": "hours", "type": "quantitative", "label": "Horas", "format": "number"},
                    ],
                },
            },
            {
                "id": "hours_tag_chart",
                "title": "Horas por tag",
                "subtitle": "Exibe as 15 maiores categorias de horas no snapshot.",
                "type": "bar",
                "dataset": "hours_by_tag_top",
                "sourceId": "clockify_tag_source",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "tag_name", "type": "nominal", "label": "Tag"},
                    "y": {"field": "hours", "type": "quantitative", "label": "Horas"},
                    "tooltip": [
                        {"field": "foco_flag", "type": "nominal", "label": "Foco"},
                        {"field": "hours", "type": "quantitative", "label": "Horas", "format": "number"},
                    ],
                },
            },
            {
                "id": "efficiency_chart",
                "title": "Eficiência da sprint",
                "subtitle": "Proporção de tickets planejados no início que foram concluídos.",
                "type": "bar",
                "dataset": "tickets_by_sprint",
                "sourceId": "jira_sprint_source",
                "valueFormat": "percent",
                "encodings": {
                    "x": {"field": "sprint_name", "type": "nominal", "label": "Sprint"},
                    "y": {"field": "eficiencia_sprint", "type": "quantitative", "label": "Eficiência", "format": "percent"},
                    "tooltip": [
                        {"field": "tickets_planejados_inicio", "type": "quantitative", "label": "Planejados"},
                        {"field": "tickets_planejados_concluidos", "type": "quantitative", "label": "Planejados concluídos"},
                    ],
                },
            },
        ],
        "tables": [
            {
                "id": "squad_table",
                "title": "Horas por squad do colaborador",
                "subtitle": "Total de horas no grão de lançamento, sem duplicação por tag ou sprint.",
                "dataset": "hours_by_squad",
                "sourceId": "clockify_entry_source",
                "defaultSort": {"field": "hours", "direction": "desc"},
                "columns": [
                    {"field": "squad_name", "label": "Squad", "type": "text"},
                    {"field": "hours", "label": "Horas", "format": "number"},
                ],
            },
            {
                "id": "tag_sprint_table",
                "title": "Horas por tag e sprint",
                "subtitle": "Base para filtros granulares como Dev em uma sprint específica.",
                "dataset": "hours_by_tag_sprint",
                "sourceId": "clockify_sprint_source",
                "defaultSort": {"field": "hours", "direction": "desc"},
                "columns": [
                    {"field": "sprint_name", "label": "Sprint", "type": "text"},
                    {"field": "tag_name", "label": "Tag", "type": "text"},
                    {"field": "foco_flag", "label": "Foco", "type": "text"},
                    {"field": "assignment_status", "label": "Atribuição", "type": "text"},
                    {"field": "hours", "label": "Horas", "format": "number"},
                ],
            },
        ],
        "sources": sources,
        "blocks": [
            {
                "id": "definition",
                "type": "markdown",
                "body": (
                    "## Como ler este painel\n\n"
                    "- O total de horas vem diretamente da fato de lançamentos.\n"
                    "- Horas por tag podem superar o total porque lançamentos com múltiplas tags "
                    "contam integralmente em cada tag.\n"
                    "- O percentual de foco exclui `Sem Papel Definido`.\n"
                    "- A eficiência usa o histórico do Jira para identificar o planejamento no início da sprint."
                ),
            },
            {
                "id": "clockify_metrics",
                "type": "metric-strip",
                "cardIds": [
                    "hours_total_card",
                    "engineering_card",
                    "dev_card",
                    "support_card",
                    "focus_card",
                ],
            },
            {
                "id": "jira_metrics",
                "type": "metric-strip",
                "cardIds": [
                    "tickets_total_card",
                    "tickets_done_card",
                    "planned_card",
                    "planned_done_card",
                    "efficiency_card",
                ],
            },
            {"id": "hours_sprint", "type": "chart", "chartId": "hours_sprint_chart"},
            {"id": "hours_tag", "type": "chart", "chartId": "hours_tag_chart"},
            {"id": "efficiency", "type": "chart", "chartId": "efficiency_chart"},
            {"id": "squads", "type": "table", "tableId": "squad_table"},
            {"id": "tag_sprint", "type": "table", "tableId": "tag_sprint_table"},
        ],
    }


def _sources(generated_at: str) -> list[dict[str, Any]]:
    return [
        _source(
            "clockify_kpi_source",
            "KPIs Clockify — fato e tags",
            "SELECT * FROM vw_clockify_entry_detail; SELECT * FROM vw_clockify_entry_tag_detail;",
            "Soma de duração no grão de lançamento e cálculos derivados da relação lançamento-tag.",
            ["vw_clockify_entry_detail", "vw_clockify_entry_tag_detail"],
            generated_at,
            [
                "Horas totais = soma de duration_seconds / 3600 na fato de lançamentos.",
                "Horas Engenharia = tags Análise e Levantamento de Requisitos, QA, Dev e Dev-Check.",
                "% Apoio à Entrega = (QA + Dev-Check) / Horas Engenharia.",
                "% Horas Foco = Dentro do Foco / (Dentro do Foco + Fora do Foco).",
            ],
        ),
        _source(
            "clockify_entry_source",
            "Horas Clockify no grão de lançamento",
            "SELECT * FROM vw_clockify_entry_detail;",
            "Fonte para total sem duplicação e horas por squad do colaborador.",
            ["vw_clockify_entry_detail"],
            generated_at,
            ["Cada linha representa um lançamento Clockify."],
        ),
        _source(
            "clockify_tag_source",
            "Horas Clockify por tag",
            "SELECT * FROM vw_clockify_entry_tag_detail;",
            "Fonte para a relação lançamento-tag e o detalhamento de foco.",
            ["vw_clockify_entry_tag_detail"],
            generated_at,
            ["Lançamentos com múltiplas tags contam integralmente em cada tag."],
        ),
        _source(
            "clockify_sprint_source",
            "Horas Clockify por sprint",
            "SELECT * FROM vw_clockify_entry_sprint_detail;",
            "Fonte para atribuições de sprint e cruzamento tag × sprint.",
            ["vw_clockify_entry_sprint_detail"],
            generated_at,
            ["O snapshot considera atribuições com status atribuído por padrão."],
        ),
        _source(
            "jira_sprint_source",
            "Execução Jira por sprint",
            "SELECT * FROM vw_jira_ticket_sprint_detail;",
            "Fonte para tickets concluídos, planejamento e eficiência das sprints.",
            ["vw_jira_ticket_sprint_detail"],
            generated_at,
            ["Eficiência = tickets planejados concluídos / tickets planejados no início."],
        ),
    ]


def _source(
    source_id: str,
    label: str,
    sql: str,
    description: str,
    tables_used: list[str],
    executed_at: str,
    metric_definitions: list[str],
) -> dict[str, Any]:
    return {
        "id": source_id,
        "label": label,
        "path": "queries/metrics.py",
        "query": {
            "engine": "PostgreSQL",
            "language": "Python/SQLAlchemy",
            "id": source_id,
            "sql": sql,
            "description": description,
            "executed_at": executed_at,
            "tables_used": tables_used,
            "metric_definitions": metric_definitions,
        },
    }


if __name__ == "__main__":
    print(write_artifact())
