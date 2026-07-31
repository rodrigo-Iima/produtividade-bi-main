"""Incremental daily reconciliation between Flow point and Clockify hours."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from clients.flow_dto import FLOW_TIMEZONE
from config.settings import (
    FLOW_RECONCILIATION_IGNORED_PERSON_IDS,
    HOURS_COMPETENCE_CLOSING_DAY,
    HOURS_RECONCILIATION_LOOKBACK_DAYS,
    HOURS_RECONCILIATION_TOLERANCE_MINUTES,
)
from models.dim_colaborador import DimColaborador  # noqa: F401
from models.dim_flow_pessoa import DimFlowPessoa
from models.dim_squad import DimSquad  # noqa: F401
from models.fato_clockify_entry import FatoClockifyEntry
from models.fato_conferencia_horas_dia import FatoConferenciaHorasDia
from models.fato_flow_dia import FatoFlowDia
from models.fato_flow_intervalo import FatoFlowIntervalo
from models.fato_flow_marcacao import FatoFlowMarcacao
from models.hist_conferencia_horas_dia import HistConferenciaHorasDia


@dataclass(frozen=True, slots=True)
class _PointAggregate:
    mark_count: int = 0
    interval_count: int = 0
    worked_seconds: int = 0


@dataclass(frozen=True, slots=True)
class _ClockifyAggregate:
    entry_count: int = 0
    seconds: int = 0


CURRENT_VALUE_FIELDS = (
    "flow_person_id",
    "flow_covered",
    "flow_day_kind",
    "point_day_exists",
    "point_mark_count",
    "point_interval_count",
    "point_worked_seconds",
    "point_complete",
    "clockify_entry_count",
    "clockify_seconds",
    "delta_seconds",
    "tolerance_seconds",
    "within_tolerance",
    "adjustment_deadline",
    "reconciliation_status",
)


class HoursReconciliationService:
    """Maintain the current daily truth and its change audit trail."""

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        lookback_days: int = HOURS_RECONCILIATION_LOOKBACK_DAYS,
        tolerance_minutes: int = HOURS_RECONCILIATION_TOLERANCE_MINUTES,
        competence_closing_day: int = HOURS_COMPETENCE_CLOSING_DAY,
        ignored_flow_person_ids: frozenset[str] = (
            FLOW_RECONCILIATION_IGNORED_PERSON_IDS
        ),
    ):
        if (
            lookback_days < 0
            or tolerance_minutes < 0
        ):
            raise ValueError("Janelas de conferência não podem ser negativas")
        if not 1 <= competence_closing_day <= 31:
            raise ValueError(
                "Dia de fechamento da competência deve estar entre 1 e 31"
            )
        self._session_factory = session_factory
        self.lookback_days = lookback_days
        self.tolerance_seconds = tolerance_minutes * 60
        self.competence_closing_day = competence_closing_day
        self.ignored_flow_person_ids = frozenset(
            ignored_flow_person_ids
        )

    def run(
        self,
        as_of: datetime | None = None,
        start_date: date | None = None,
    ) -> dict[str, int]:
        session_factory = self._session_factory
        if session_factory is None:
            from database.connection import SessionLocal

            session_factory = SessionLocal

        session = session_factory()
        try:
            result = self.reconcile(
                session,
                as_of=as_of,
                start_date=start_date,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def reconcile(
        self,
        session: Session,
        as_of: datetime | None = None,
        start_date: date | None = None,
    ) -> dict[str, int]:
        calculated_at = as_of or datetime.now(timezone.utc)
        if calculated_at.tzinfo is None:
            raise ValueError("as_of deve possuir fuso horário")
        as_of_date = calculated_at.astimezone(FLOW_TIMEZONE).date()
        window_start = start_date or (
            as_of_date - timedelta(days=self.lookback_days)
        )
        if window_start > as_of_date:
            raise ValueError("start_date não pode ser posterior a as_of")

        mapping_rows = session.execute(
            select(
                DimFlowPessoa.flow_person_id,
                DimFlowPessoa.clockify_user_id,
            ).where(
                DimFlowPessoa.is_active.is_(True),
                DimFlowPessoa.mapping_status == "mapped",
                DimFlowPessoa.clockify_user_id.is_not(None),
            )
        ).all()
        flow_to_user = {
            flow_person_id: user_id
            for flow_person_id, user_id in mapping_rows
        }
        user_to_flow = {
            user_id: flow_person_id
            for flow_person_id, user_id in mapping_rows
        }
        if not flow_to_user:
            return {
                "records_evaluated": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "history_written": 0,
            }

        all_days = session.scalars(
            select(FatoFlowDia).where(
                FatoFlowDia.flow_person_id.in_(flow_to_user),
            )
        ).all()
        coverage_by_user: dict[str, tuple[date, date]] = {}
        for day in all_days:
            user_id = flow_to_user[day.flow_person_id]
            coverage = coverage_by_user.get(user_id)
            if coverage is None:
                coverage_by_user[user_id] = (
                    day.work_date,
                    day.work_date,
                )
            else:
                coverage_by_user[user_id] = (
                    min(coverage[0], day.work_date),
                    max(coverage[1], day.work_date),
                )
        days = [
            day
            for day in all_days
            if window_start <= day.work_date <= as_of_date
        ]
        days_by_key = {
            (flow_to_user[day.flow_person_id], day.work_date): day
            for day in days
        }
        point_by_key = self._point_aggregates(
            session,
            flow_to_user,
            window_start,
            as_of_date,
        )
        clockify_by_key = self._clockify_aggregates(
            session,
            user_to_flow,
            window_start,
            as_of_date,
        )
        existing_rows = session.scalars(
            select(FatoConferenciaHorasDia).where(
                FatoConferenciaHorasDia.user_id.in_(user_to_flow),
                FatoConferenciaHorasDia.work_date.between(
                    window_start,
                    as_of_date,
                ),
            )
        ).all()
        existing_by_key = {
            (row.user_id, row.work_date): row
            for row in existing_rows
        }

        active_point_keys = {
            key
            for key, point in point_by_key.items()
            if point.mark_count > 0
        }
        keys = (
            active_point_keys
            | set(clockify_by_key)
            | set(existing_by_key)
        )

        counts = {
            "records_evaluated": len(keys),
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "history_written": 0,
        }
        for user_id, work_date in sorted(keys):
            day = days_by_key.get((user_id, work_date))
            point = point_by_key.get(
                (user_id, work_date),
                _PointAggregate(),
            )
            clockify = clockify_by_key.get(
                (user_id, work_date),
                _ClockifyAggregate(),
            )
            flow_person_id = user_to_flow[user_id]
            deadline = competence_adjustment_deadline(
                work_date,
                self.competence_closing_day,
            )
            coverage = coverage_by_user.get(user_id)
            flow_covered = bool(
                coverage is not None
                and coverage[0] <= work_date <= coverage[1]
            )
            point_complete = bool(
                day is not None
                and point.mark_count > 0
                and point.mark_count % 2 == 0
                and not day.pending_calculation
                and not day.errors
            )
            delta_seconds = clockify.seconds - point.worked_seconds
            within_tolerance = bool(
                point_complete
                and clockify.entry_count > 0
                and abs(delta_seconds) <= self.tolerance_seconds
            )
            values = {
                "flow_person_id": flow_person_id,
                "flow_covered": flow_covered,
                "flow_day_kind": day.kind if day is not None else None,
                "point_day_exists": day is not None,
                "point_mark_count": point.mark_count,
                "point_interval_count": point.interval_count,
                "point_worked_seconds": point.worked_seconds,
                "point_complete": point_complete,
                "clockify_entry_count": clockify.entry_count,
                "clockify_seconds": clockify.seconds,
                "delta_seconds": delta_seconds,
                "tolerance_seconds": self.tolerance_seconds,
                "within_tolerance": within_tolerance,
                "adjustment_deadline": deadline,
                "reconciliation_status": classify_daily_reconciliation(
                    work_date=work_date,
                    as_of_date=as_of_date,
                    adjustment_deadline=deadline,
                    flow_covered=flow_covered,
                    point_mark_count=point.mark_count,
                    point_complete=point_complete,
                    point_worked_seconds=point.worked_seconds,
                    clockify_entry_count=clockify.entry_count,
                    clockify_seconds=clockify.seconds,
                    flow_day_kind=(
                        day.kind if day is not None else None
                    ),
                    tolerance_seconds=self.tolerance_seconds,
                    ignored=(
                        flow_person_id
                        in self.ignored_flow_person_ids
                    ),
                ),
                "point_collected_at": (
                    day.collected_at if day is not None else None
                ),
            }
            current = existing_by_key.get((user_id, work_date))
            change_type = "created"
            if current is None:
                current = FatoConferenciaHorasDia(
                    user_id=user_id,
                    work_date=work_date,
                    as_of_date=as_of_date,
                    calculated_at=calculated_at,
                    **values,
                )
                session.add(current)
                counts["created"] += 1
            elif _row_changed(current, values):
                change_type = "updated"
                for field, value in values.items():
                    setattr(current, field, value)
                current.as_of_date = as_of_date
                current.calculated_at = calculated_at
                counts["updated"] += 1
            else:
                current.point_collected_at = values["point_collected_at"]
                current.as_of_date = as_of_date
                current.calculated_at = calculated_at
                counts["unchanged"] += 1
                continue

            session.add(
                HistConferenciaHorasDia(
                    user_id=user_id,
                    work_date=work_date,
                    change_type=change_type,
                    as_of_date=as_of_date,
                    recorded_at=calculated_at,
                    **values,
                )
            )
            counts["history_written"] += 1

        session.flush()
        return counts

    @staticmethod
    def _point_aggregates(
        session: Session,
        flow_to_user: dict[str, str],
        window_start: date,
        as_of_date: date,
    ) -> dict[tuple[str, date], _PointAggregate]:
        mark_rows = session.execute(
            select(
                FatoFlowMarcacao.flow_person_id,
                FatoFlowMarcacao.work_date,
                func.count().label("mark_count"),
            )
            .where(
                FatoFlowMarcacao.flow_person_id.in_(flow_to_user),
                FatoFlowMarcacao.work_date.between(
                    window_start,
                    as_of_date,
                ),
            )
            .group_by(
                FatoFlowMarcacao.flow_person_id,
                FatoFlowMarcacao.work_date,
            )
        ).all()
        interval_rows = session.execute(
            select(
                FatoFlowIntervalo.flow_person_id,
                FatoFlowIntervalo.work_date,
                func.count().label("interval_count"),
                func.coalesce(
                    func.sum(FatoFlowIntervalo.duration_seconds),
                    0,
                ).label("worked_seconds"),
            )
            .where(
                FatoFlowIntervalo.flow_person_id.in_(flow_to_user),
                FatoFlowIntervalo.work_date.between(
                    window_start,
                    as_of_date,
                ),
            )
            .group_by(
                FatoFlowIntervalo.flow_person_id,
                FatoFlowIntervalo.work_date,
            )
        ).all()
        result = {
            (flow_to_user[flow_person_id], work_date): _PointAggregate(
                mark_count=int(mark_count),
            )
            for flow_person_id, work_date, mark_count in mark_rows
        }
        for (
            flow_person_id,
            work_date,
            interval_count,
            worked_seconds,
        ) in interval_rows:
            key = (flow_to_user[flow_person_id], work_date)
            current = result.get(key, _PointAggregate())
            result[key] = _PointAggregate(
                mark_count=current.mark_count,
                interval_count=int(interval_count),
                worked_seconds=int(worked_seconds),
            )
        return result

    @staticmethod
    def _clockify_aggregates(
        session: Session,
        user_to_flow: dict[str, str],
        window_start: date,
        as_of_date: date,
    ) -> dict[tuple[str, date], _ClockifyAggregate]:
        local_date = func.coalesce(
            FatoClockifyEntry.entry_date_local,
            FatoClockifyEntry.entry_date,
        )
        local_window_start = datetime.combine(
            window_start,
            time.min,
            tzinfo=FLOW_TIMEZONE,
        )
        local_window_end = datetime.combine(
            as_of_date + timedelta(days=1),
            time.min,
            tzinfo=FLOW_TIMEZONE,
        )
        utc_window_start = local_window_start.astimezone(timezone.utc)
        utc_window_end = local_window_end.astimezone(timezone.utc)
        entries = session.scalars(
            select(FatoClockifyEntry).where(
                FatoClockifyEntry.user_id.in_(user_to_flow),
                or_(
                    and_(
                        FatoClockifyEntry.started_at.is_not(None),
                        FatoClockifyEntry.ended_at.is_not(None),
                        FatoClockifyEntry.ended_at > utc_window_start,
                        FatoClockifyEntry.started_at < utc_window_end,
                    ),
                    local_date.between(window_start, as_of_date),
                ),
            )
        ).all()

        totals: dict[tuple[str, date], list[int]] = defaultdict(
            lambda: [0, 0]
        )
        for entry in entries:
            started_at = _as_aware_utc(entry.started_at)
            ended_at = _as_aware_utc(entry.ended_at)
            if (
                started_at is None
                or ended_at is None
                or ended_at <= started_at
            ):
                fallback_date = entry.entry_date_local or entry.entry_date
                if window_start <= fallback_date <= as_of_date:
                    totals[(entry.user_id, fallback_date)][0] += 1
                    totals[(entry.user_id, fallback_date)][1] += int(
                        entry.duration_seconds
                    )
                continue

            cursor = max(
                started_at.astimezone(FLOW_TIMEZONE),
                local_window_start,
            )
            local_end = min(
                ended_at.astimezone(FLOW_TIMEZONE),
                local_window_end,
            )
            while cursor < local_end:
                next_midnight = datetime.combine(
                    cursor.date() + timedelta(days=1),
                    time.min,
                    tzinfo=FLOW_TIMEZONE,
                )
                segment_end = min(local_end, next_midnight)
                segment_seconds = round(
                    (segment_end - cursor).total_seconds()
                )
                if segment_seconds > 0:
                    key = (entry.user_id, cursor.date())
                    totals[key][0] += 1
                    totals[key][1] += segment_seconds
                cursor = segment_end

        return {
            key: _ClockifyAggregate(
                entry_count=values[0],
                seconds=values[1],
            )
            for key, values in totals.items()
        }


def classify_daily_reconciliation(
    *,
    work_date: date,
    as_of_date: date,
    adjustment_deadline: date,
    flow_covered: bool = True,
    point_mark_count: int,
    point_complete: bool,
    point_worked_seconds: int,
    clockify_entry_count: int,
    clockify_seconds: int,
    flow_day_kind: str | None = None,
    tolerance_seconds: int = 0,
    ignored: bool = False,
) -> str:
    """Classify one comparison without hiding its signed hour difference."""
    if ignored:
        return "ignorado_regra_negocio"
    if point_mark_count == 0 and clockify_entry_count == 0:
        return "sem_movimento"
    if not flow_covered:
        return "fora_cobertura_flow"
    if work_date >= as_of_date:
        return "em_andamento"

    within_window = as_of_date <= adjustment_deadline
    if (
        clockify_entry_count > 0
        and _is_nonworking_flow_day(flow_day_kind)
    ):
        return "clockify_em_dia_nao_trabalhado"
    if point_mark_count == 0 or not point_complete:
        return (
            "aguardando_ajuste_ponto"
            if within_window
            else "pendencia_ponto_vencida"
        )
    if clockify_entry_count == 0:
        return (
            "aguardando_lancamento_clockify"
            if within_window
            else "pendencia_clockify_vencida"
        )
    delta_seconds = clockify_seconds - point_worked_seconds
    if abs(delta_seconds) > tolerance_seconds:
        direction = (
            "clockify_maior" if delta_seconds > 0 else "clockify_menor"
        )
        return (
            f"{direction}_no_prazo"
            if within_window
            else f"{direction}_vencido"
        )
    return "conferido"


def competence_adjustment_deadline(
    work_date: date,
    closing_day: int,
) -> date:
    """Return the fixed closing date in the work date's calendar month."""
    if not 1 <= closing_day <= 31:
        raise ValueError("closing_day deve estar entre 1 e 31")
    last_day = monthrange(work_date.year, work_date.month)[1]
    return date(
        work_date.year,
        work_date.month,
        min(closing_day, last_day),
    )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_nonworking_flow_day(kind: str | None) -> bool:
    normalized = (kind or "").strip().casefold()
    return normalized in {
        "férias",
        "ferias",
        "vacation",
        "repouso remunerado",
        "paid rest",
        "rest_day",
    }


def _row_changed(
    current: FatoConferenciaHorasDia,
    values: dict,
) -> bool:
    return any(
        getattr(current, field) != values[field]
        for field in CURRENT_VALUE_FIELDS
    )
