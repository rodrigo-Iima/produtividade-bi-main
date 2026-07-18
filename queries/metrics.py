"""Metrics and drill-down queries for the Phase 3 analytical layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, exists, func, literal, select

from database.connection import SessionLocal
from etl.sprint_scope import ALLOWED_SPRINT_STATES, SPRINT_START_AFTER
from models.bridge_clockify_entry_issue import BridgeClockifyEntryIssue
from models.bridge_clockify_entry_sprint import BridgeClockifyEntrySprint
from models.bridge_clockify_entry_tag import BridgeClockifyEntryTag
from models.dim_colaborador import DimColaborador
from models.dim_squad import DimSquad
from models.dim_sprint import DimSprint
from models.dim_status import DimStatus
from models.dim_tag import DimTag
from models.dim_ticket_jira import DimTicketJira
from models.fato_clockify_entry import FatoClockifyEntry
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from providers.tags_provider import normalize_tag


@dataclass(frozen=True)
class HoursFilters:
    """Optional filters shared by all Clockify metrics."""

    start_date: date | None = None
    end_date: date | None = None
    user_id: str | None = None
    squad_id: int | None = None
    squad_name: str | None = None
    papel: str | None = None
    project_name: str | None = None
    tag: str | None = None
    foco_flag: str | None = None
    sprint_id: int | None = None
    sprint_name: str | None = None
    issue_key: str | None = None
    assignment_status: str | None = None
    include_ambiguous: bool = False


@dataclass(frozen=True)
class TicketFilters:
    """Optional filters shared by Jira ticket/sprint metrics."""

    sprint_id: int | None = None
    sprint_name: str | None = None
    project_key: str | None = None
    squad_jira: str | None = None
    status_original: str | None = None
    status_grouped: str | None = None
    issue_key: str | None = None
    start_date: date | None = None
    end_date: date | None = None


def total_hours(filters: HoursFilters | None = None) -> float:
    """Return total recorded hours without tag/sprint join duplication."""
    filters = filters or HoursFilters()
    with SessionLocal() as session:
        statement = select(
            func.coalesce(func.sum(FatoClockifyEntry.duration_seconds), 0)
            / literal(3600.0)
        ).select_from(FatoClockifyEntry).where(*_entry_conditions(filters))
        value = session.execute(statement).scalar_one()
    return _as_float(value)


def hours_by_collaborator(filters: HoursFilters | None = None) -> list[dict[str, Any]]:
    """Group hours by collaborator at the canonical entry grain."""
    filters = filters or HoursFilters()
    hours = _hours_expression()
    with SessionLocal() as session:
        statement = (
            select(
                DimColaborador.user_id,
                DimColaborador.name.label("collaborator_name"),
                DimColaborador.papel,
                DimSquad.squad_id,
                DimSquad.nome.label("squad_name"),
                hours.label("hours"),
            )
            .select_from(FatoClockifyEntry)
            .join(DimColaborador, DimColaborador.user_id == FatoClockifyEntry.user_id)
            .outerjoin(DimSquad, DimSquad.squad_id == DimColaborador.squad_id)
            .where(*_entry_conditions(filters))
            .group_by(
                DimColaborador.user_id,
                DimColaborador.name,
                DimColaborador.papel,
                DimSquad.squad_id,
                DimSquad.nome,
            )
            .order_by(hours.desc(), DimColaborador.name)
        )
        return _rows(session.execute(statement).mappings().all())


def hours_by_tag(filters: HoursFilters | None = None) -> list[dict[str, Any]]:
    """Group hours by tag; multi-tag entries count fully in each tag."""
    filters = filters or HoursFilters()
    hours = _hours_expression()
    with SessionLocal() as session:
        statement = (
            select(
                DimTag.tag_id,
                DimTag.nome.label("tag_name"),
                DimTag.nome_normalizado.label("tag_name_normalized"),
                BridgeClockifyEntryTag.foco_flag,
                hours.label("hours"),
            )
            .select_from(FatoClockifyEntry)
            .join(
                BridgeClockifyEntryTag,
                BridgeClockifyEntryTag.entry_id == FatoClockifyEntry.entry_id,
            )
            .join(DimTag, DimTag.tag_id == BridgeClockifyEntryTag.tag_id)
            .where(
                *_entry_conditions(filters),
                *_tag_dimension_conditions(filters),
            )
            .group_by(
                DimTag.tag_id,
                DimTag.nome,
                DimTag.nome_normalizado,
                BridgeClockifyEntryTag.foco_flag,
            )
            .order_by(hours.desc(), DimTag.nome)
        )
        return _rows(session.execute(statement).mappings().all())


def hours_by_squad(filters: HoursFilters | None = None) -> list[dict[str, Any]]:
    """Group total entry hours by the collaborator's canonical squad."""
    filters = filters or HoursFilters()
    hours = _hours_expression()
    with SessionLocal() as session:
        statement = (
            select(
                DimSquad.squad_id,
                DimSquad.nome.label("squad_name"),
                hours.label("hours"),
            )
            .select_from(FatoClockifyEntry)
            .join(DimColaborador, DimColaborador.user_id == FatoClockifyEntry.user_id)
            .outerjoin(DimSquad, DimSquad.squad_id == DimColaborador.squad_id)
            .where(*_entry_conditions(filters))
            .group_by(DimSquad.squad_id, DimSquad.nome)
            .order_by(hours.desc(), DimSquad.nome)
        )
        return _rows(session.execute(statement).mappings().all())


def hours_by_sprint(filters: HoursFilters | None = None) -> list[dict[str, Any]]:
    """Group hours by the sprint attribution generated by the ETL."""
    filters = filters or HoursFilters()
    hours = _hours_expression()
    status_condition = _sprint_status_condition(filters, BridgeClockifyEntrySprint)
    with SessionLocal() as session:
        statement = (
            select(
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                DimSprint.sprint_start,
                DimSprint.sprint_end,
                BridgeClockifyEntrySprint.assignment_status,
                hours.label("hours"),
            )
            .select_from(FatoClockifyEntry)
            .join(
                BridgeClockifyEntrySprint,
                BridgeClockifyEntrySprint.entry_id == FatoClockifyEntry.entry_id,
            )
            .join(DimSprint, DimSprint.sprint_id == BridgeClockifyEntrySprint.sprint_id)
            .where(
                *_entry_conditions(filters, exclude_sprint_filter=True),
                *_sprint_dimension_conditions(filters),
                *_sprint_scope_conditions(),
                status_condition,
            )
            .group_by(
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                DimSprint.sprint_start,
                DimSprint.sprint_end,
                BridgeClockifyEntrySprint.assignment_status,
            )
            .order_by(DimSprint.sprint_start, DimSprint.sprint_id)
        )
        return _rows(session.execute(statement).mappings().all())


def hours_by_tag_and_sprint(filters: HoursFilters | None = None) -> list[dict[str, Any]]:
    """Group hours by tag and sprint with all filters applied."""
    filters = filters or HoursFilters()
    hours = _hours_expression()
    status_condition = _sprint_status_condition(filters, BridgeClockifyEntrySprint)
    with SessionLocal() as session:
        statement = (
            select(
                DimTag.tag_id,
                DimTag.nome.label("tag_name"),
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                BridgeClockifyEntryTag.foco_flag,
                BridgeClockifyEntrySprint.assignment_status,
                hours.label("hours"),
            )
            .select_from(FatoClockifyEntry)
            .join(
                BridgeClockifyEntryTag,
                BridgeClockifyEntryTag.entry_id == FatoClockifyEntry.entry_id,
            )
            .join(DimTag, DimTag.tag_id == BridgeClockifyEntryTag.tag_id)
            .join(
                BridgeClockifyEntrySprint,
                BridgeClockifyEntrySprint.entry_id == FatoClockifyEntry.entry_id,
            )
            .join(DimSprint, DimSprint.sprint_id == BridgeClockifyEntrySprint.sprint_id)
            .where(
                *_entry_conditions(filters, exclude_sprint_filter=True),
                *_tag_dimension_conditions(filters),
                *_sprint_dimension_conditions(filters),
                *_sprint_scope_conditions(),
                status_condition,
            )
            .group_by(
                DimTag.tag_id,
                DimTag.nome,
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                BridgeClockifyEntryTag.foco_flag,
                BridgeClockifyEntrySprint.assignment_status,
            )
            .order_by(DimSprint.sprint_start, DimTag.nome)
        )
        return _rows(session.execute(statement).mappings().all())


def clockify_kpis(filters: HoursFilters | None = None) -> dict[str, Any]:
    """Return the named Clockify KPIs from the tag-level analytical grain."""
    filters = filters or HoursFilters()
    tag_rows = hours_by_tag(filters)

    engineering_tags = {
        normalize_tag("Análise e Levantamento de Requisitos"),
        normalize_tag("QA"),
        normalize_tag("Dev"),
        normalize_tag("Dev-Check"),
    }
    support_tags = {normalize_tag("QA"), normalize_tag("Dev-Check")}

    horas_engenharia = sum(
        row["hours"]
        for row in tag_rows
        if row["tag_name_normalized"] in engineering_tags
    )
    horas_dev = sum(
        row["hours"]
        for row in tag_rows
        if row["tag_name_normalized"] == normalize_tag("Dev")
    )
    horas_apoio_entrega = sum(
        row["hours"]
        for row in tag_rows
        if row["tag_name_normalized"] in support_tags
    )
    horas_dentro_foco = sum(
        row["hours"] for row in tag_rows if row["foco_flag"] == "Dentro do Foco"
    )
    horas_total_foco = sum(
        row["hours"]
        for row in tag_rows
        if row["foco_flag"] in {"Dentro do Foco", "Fora do Foco"}
    )

    return {
        "horas_total": total_hours(filters),
        "horas_engenharia": horas_engenharia,
        "horas_dev": horas_dev,
        "horas_apoio_entrega": horas_apoio_entrega,
        "percentual_apoio_entrega": (
            horas_apoio_entrega / horas_engenharia if horas_engenharia else None
        ),
        "horas_dentro_foco": horas_dentro_foco,
        "horas_total_foco": horas_total_foco,
        "percentual_horas_foco": (
            horas_dentro_foco / horas_total_foco if horas_total_foco else None
        ),
    }


def ticket_metrics(filters: TicketFilters | None = None) -> dict[str, Any]:
    """Return Jira ticket totals and sprint-planning efficiency."""
    filters = filters or TicketFilters()
    status_group = _status_group_expression()
    planned = FatoJiraTicketSprint.planejado_no_inicio.is_(True)
    completed = status_group == "Concluído"
    with SessionLocal() as session:
        statement = (
            select(
                func.count(func.distinct(FatoJiraTicketSprint.issue_key)).label("tickets_total"),
                func.count(func.distinct(case((completed, FatoJiraTicketSprint.issue_key)))).label(
                    "tickets_concluidos"
                ),
                func.coalesce(func.sum(case((planned, 1), else_=0)), 0).label(
                    "tickets_planejados_inicio"
                ),
                func.coalesce(
                    func.sum(case((and_(planned, completed), 1), else_=0)), 0
                ).label("tickets_planejados_concluidos"),
            )
            .select_from(FatoJiraTicketSprint)
            .join(DimTicketJira, DimTicketJira.issue_key == FatoJiraTicketSprint.issue_key)
            .join(DimSprint, DimSprint.sprint_id == FatoJiraTicketSprint.sprint_id)
            .outerjoin(DimStatus, DimStatus.status_original == DimTicketJira.status_original)
            .where(*_ticket_conditions(filters, status_group))
        )
        row = dict(session.execute(statement).mappings().one())

    row["tickets_total"] = int(row["tickets_total"] or 0)
    row["tickets_concluidos"] = int(row["tickets_concluidos"] or 0)
    row["tickets_planejados_inicio"] = int(row["tickets_planejados_inicio"] or 0)
    row["tickets_planejados_concluidos"] = int(row["tickets_planejados_concluidos"] or 0)
    planned_count = row["tickets_planejados_inicio"]
    row["eficiencia_sprint"] = (
        row["tickets_planejados_concluidos"] / planned_count
        if planned_count
        else None
    )
    return row


def tickets_by_sprint(filters: TicketFilters | None = None) -> list[dict[str, Any]]:
    """Return ticket planning and completion metrics for each sprint."""
    filters = filters or TicketFilters()
    status_group = _status_group_expression()
    planned = FatoJiraTicketSprint.planejado_no_inicio.is_(True)
    completed = status_group == "Concluído"
    with SessionLocal() as session:
        statement = (
            select(
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                DimSprint.sprint_start,
                DimSprint.sprint_end,
                func.count(func.distinct(FatoJiraTicketSprint.issue_key)).label("tickets_total"),
                func.count(func.distinct(case((completed, FatoJiraTicketSprint.issue_key)))).label(
                    "tickets_concluidos"
                ),
                func.coalesce(func.sum(case((planned, 1), else_=0)), 0).label(
                    "tickets_planejados_inicio"
                ),
                func.coalesce(
                    func.sum(case((and_(planned, completed), 1), else_=0)), 0
                ).label("tickets_planejados_concluidos"),
            )
            .select_from(FatoJiraTicketSprint)
            .join(DimTicketJira, DimTicketJira.issue_key == FatoJiraTicketSprint.issue_key)
            .join(DimSprint, DimSprint.sprint_id == FatoJiraTicketSprint.sprint_id)
            .outerjoin(DimStatus, DimStatus.status_original == DimTicketJira.status_original)
            .where(*_ticket_conditions(filters, status_group))
            .group_by(
                DimSprint.sprint_id,
                DimSprint.sprint_name,
                DimSprint.sprint_start,
                DimSprint.sprint_end,
            )
            .order_by(DimSprint.sprint_start, DimSprint.sprint_id)
        )
        rows = _rows(session.execute(statement).mappings().all())

    for row in rows:
        planned_count = row["tickets_planejados_inicio"]
        row["eficiencia_sprint"] = (
            row["tickets_planejados_concluidos"] / planned_count
            if planned_count
            else None
        )
    return rows


def _entry_conditions(
    filters: HoursFilters,
    *,
    exclude_sprint_filter: bool = False,
) -> list[Any]:
    conditions: list[Any] = []
    if filters.start_date is not None:
        conditions.append(FatoClockifyEntry.entry_date >= filters.start_date)
    if filters.end_date is not None:
        conditions.append(FatoClockifyEntry.entry_date <= filters.end_date)
    if filters.user_id is not None:
        conditions.append(FatoClockifyEntry.user_id == filters.user_id)
    if filters.project_name is not None:
        conditions.append(FatoClockifyEntry.project_name == filters.project_name)
    if filters.issue_key is not None:
        conditions.append(exists(
            select(1).where(
                BridgeClockifyEntryIssue.entry_id == FatoClockifyEntry.entry_id,
                BridgeClockifyEntryIssue.issue_key == filters.issue_key,
            )
        ))

    if filters.squad_id is not None or filters.squad_name is not None or filters.papel is not None:
        collaborator_query = select(1).select_from(DimColaborador).outerjoin(
            DimSquad, DimSquad.squad_id == DimColaborador.squad_id
        ).where(DimColaborador.user_id == FatoClockifyEntry.user_id)
        if filters.squad_id is not None:
            collaborator_query = collaborator_query.where(DimSquad.squad_id == filters.squad_id)
        if filters.squad_name is not None:
            collaborator_query = collaborator_query.where(DimSquad.nome == filters.squad_name)
        if filters.papel is not None:
            collaborator_query = collaborator_query.where(DimColaborador.papel == filters.papel)
        conditions.append(exists(collaborator_query))

    if filters.tag is not None or filters.foco_flag is not None:
        tag_query = select(1).select_from(BridgeClockifyEntryTag).join(
            DimTag, DimTag.tag_id == BridgeClockifyEntryTag.tag_id
        ).where(BridgeClockifyEntryTag.entry_id == FatoClockifyEntry.entry_id)
        if filters.tag is not None:
            tag_query = tag_query.where(DimTag.nome_normalizado == normalize_tag(filters.tag))
        if filters.foco_flag is not None:
            tag_query = tag_query.where(BridgeClockifyEntryTag.foco_flag == filters.foco_flag)
        conditions.append(exists(tag_query))

    if not exclude_sprint_filter and (
        filters.sprint_id is not None
        or filters.sprint_name is not None
        or filters.assignment_status is not None
    ):
        sprint_query = select(1).select_from(BridgeClockifyEntrySprint).outerjoin(
            DimSprint, DimSprint.sprint_id == BridgeClockifyEntrySprint.sprint_id
        ).where(BridgeClockifyEntrySprint.entry_id == FatoClockifyEntry.entry_id)
        if filters.sprint_id is not None:
            sprint_query = sprint_query.where(BridgeClockifyEntrySprint.sprint_id == filters.sprint_id)
        if filters.sprint_name is not None:
            sprint_query = sprint_query.where(DimSprint.sprint_name == filters.sprint_name)
        sprint_query = sprint_query.where(
            _sprint_status_condition(filters, BridgeClockifyEntrySprint)
        )
        conditions.append(exists(sprint_query))

    return conditions


def _sprint_dimension_conditions(filters: HoursFilters) -> list[Any]:
    """Apply sprint identity filters to queries already joined to dim_sprint."""
    conditions: list[Any] = []
    if filters.sprint_id is not None:
        conditions.append(DimSprint.sprint_id == filters.sprint_id)
    if filters.sprint_name is not None:
        conditions.append(DimSprint.sprint_name == filters.sprint_name)
    return conditions


def _tag_dimension_conditions(filters: HoursFilters) -> list[Any]:
    """Apply tag filters to grouped tag rows as well as to matching entries."""
    conditions: list[Any] = []
    if filters.tag is not None:
        conditions.append(DimTag.nome_normalizado == normalize_tag(filters.tag))
    if filters.foco_flag is not None:
        conditions.append(BridgeClockifyEntryTag.foco_flag == filters.foco_flag)
    return conditions


def _sprint_scope_conditions() -> list[Any]:
    """Keep sprint breakdowns aligned with the active 2026 sprint scope."""
    return [
        DimSprint.sprint_start > SPRINT_START_AFTER,
        DimSprint.sprint_start <= datetime.now(timezone.utc),
        func.upper(DimSprint.sprint_state).in_(ALLOWED_SPRINT_STATES),
    ]


def _sprint_status_condition(filters: HoursFilters, model) -> Any:
    if filters.assignment_status is not None:
        return model.assignment_status == filters.assignment_status
    if filters.include_ambiguous:
        return model.assignment_status.in_(("atribuido", "ambiguo"))
    return model.assignment_status == "atribuido"


def _hours_expression():
    return func.sum(FatoClockifyEntry.duration_seconds) / literal(3600.0)


def _status_group_expression():
    return func.coalesce(DimStatus.status_agrupado, literal("Não Classificado"))


def _ticket_conditions(filters: TicketFilters, status_group) -> list[Any]:
    conditions: list[Any] = _sprint_scope_conditions()
    if filters.sprint_id is not None:
        conditions.append(DimSprint.sprint_id == filters.sprint_id)
    if filters.sprint_name is not None:
        conditions.append(DimSprint.sprint_name == filters.sprint_name)
    if filters.project_key is not None:
        conditions.append(DimTicketJira.project_key == filters.project_key)
    if filters.squad_jira is not None:
        conditions.append(DimTicketJira.squad_jira == filters.squad_jira)
    if filters.status_original is not None:
        conditions.append(DimTicketJira.status_original == filters.status_original)
    if filters.status_grouped is not None:
        conditions.append(status_group == filters.status_grouped)
    if filters.issue_key is not None:
        conditions.append(FatoJiraTicketSprint.issue_key == filters.issue_key)
    if filters.start_date is not None:
        conditions.append(func.date(DimSprint.sprint_start) >= filters.start_date)
    if filters.end_date is not None:
        conditions.append(func.date(DimSprint.sprint_start) <= filters.end_date)
    return conditions


def _rows(rows) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(value, Decimal):
                item[key] = float(value)
        for key in ("tickets_total", "tickets_concluidos", "tickets_planejados_inicio", "tickets_planejados_concluidos"):
            if key in item and item[key] is not None:
                item[key] = int(item[key])
        result.append(item)
    return result


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
