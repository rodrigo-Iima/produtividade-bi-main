"""Transactional, idempotent loading of Flow attendance markings."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from clients.flow_client import FlowClient
from clients.flow_dto import FlowPointDay, FlowPointPeriod, FlowPoints
from models.dim_flow_pessoa import DimFlowPessoa
from models.fato_flow_dia import FatoFlowDia
from models.fato_flow_intervalo import FatoFlowIntervalo
from models.fato_flow_marcacao import FatoFlowMarcacao


class FlowPointLoadError(ValueError):
    """Raised before persistence when a point snapshot is inconsistent."""


class FlowPointLoadService:
    """Replace only the person/date slices explicitly returned by Flow."""

    def replace_returned_days(
        self,
        session: Session,
        point_snapshots: Iterable[FlowPoints],
        collected_at: datetime | None = None,
        allow_unmapped: bool = False,
    ) -> dict[str, int]:
        collected_at = collected_at or datetime.now(timezone.utc)
        if collected_at.tzinfo is None:
            raise FlowPointLoadError("collected_at deve possuir fuso horário")

        snapshots = list(point_snapshots)
        snapshots_by_person = self._validate_snapshots(
            session,
            snapshots,
            allow_unmapped=allow_unmapped,
        )
        returned_days = self._collect_returned_days(snapshots_by_person)

        dates_by_person: dict[str, list] = defaultdict(list)
        for person_id, period, day in returned_days:
            dates_by_person[person_id].append(day.work_date)

        for person_id, work_dates in dates_by_person.items():
            session.execute(
                delete(FatoFlowIntervalo)
                .where(
                    FatoFlowIntervalo.flow_person_id == person_id,
                    FatoFlowIntervalo.work_date.in_(work_dates),
                )
                .execution_options(synchronize_session=False)
            )
            session.execute(
                delete(FatoFlowMarcacao)
                .where(
                    FatoFlowMarcacao.flow_person_id == person_id,
                    FatoFlowMarcacao.work_date.in_(work_dates),
                )
                .execution_options(synchronize_session=False)
            )
            session.execute(
                delete(FatoFlowDia)
                .where(
                    FatoFlowDia.flow_person_id == person_id,
                    FatoFlowDia.work_date.in_(work_dates),
                )
                .execution_options(synchronize_session=False)
            )

        daily_rows = [
            self._daily_row(person_id, period, day, collected_at)
            for person_id, period, day in returned_days
        ]
        session.add_all(daily_rows)
        session.flush()

        marking_rows = [
            FatoFlowMarcacao(
                flow_person_id=person_id,
                work_date=day.work_date,
                order_in_day=order,
                marked_at=marked_at,
                collected_at=collected_at,
            )
            for person_id, _period, day in returned_days
            for order, marked_at in enumerate(day.moments, start=1)
        ]
        session.add_all(marking_rows)

        interval_rows = [
            FatoFlowIntervalo(
                flow_person_id=person_id,
                work_date=day.work_date,
                pair_order=pair_index + 1,
                entry_mark_order=(pair_index * 2) + 1,
                exit_mark_order=(pair_index * 2) + 2,
                started_at=day.moments[pair_index * 2],
                ended_at=day.moments[(pair_index * 2) + 1],
                duration_seconds=round(
                    (
                        day.moments[(pair_index * 2) + 1]
                        - day.moments[pair_index * 2]
                    ).total_seconds()
                ),
                collected_at=collected_at,
            )
            for person_id, _period, day in returned_days
            for pair_index in range(len(day.moments) // 2)
        ]
        session.add_all(interval_rows)
        session.flush()

        return {
            "people_received": len(snapshots),
            "people_with_returned_days": len(dates_by_person),
            "days_replaced": len(daily_rows),
            "marks_loaded": len(marking_rows),
            "intervals_loaded": len(interval_rows),
        }

    def _validate_snapshots(
        self,
        session: Session,
        snapshots: list[FlowPoints],
        allow_unmapped: bool = False,
    ) -> dict[str, FlowPoints]:
        snapshots_by_person: dict[str, FlowPoints] = {}
        for snapshot in snapshots:
            if snapshot.person_id in snapshots_by_person:
                raise FlowPointLoadError(
                    "Pessoa Flow duplicada no lote: "
                    f"{snapshot.person_id}"
                )
            snapshots_by_person[snapshot.person_id] = snapshot

        people = {
            person.flow_person_id: person
            for person in session.scalars(
                select(DimFlowPessoa).where(
                    DimFlowPessoa.flow_person_id.in_(
                        snapshots_by_person
                    )
                )
            )
        }
        for person_id in snapshots_by_person:
            person = people.get(person_id)
            if person is None:
                raise FlowPointLoadError(
                    f"Pessoa Flow inexistente: {person_id}"
                )
            if not person.is_active or (
                not allow_unmapped and person.mapping_status != "mapped"
            ):
                raise FlowPointLoadError(
                    "Pessoa Flow não está ativa e mapeada: "
                    f"{person_id}"
                )

        self._collect_returned_days(snapshots_by_person)
        return snapshots_by_person

    @staticmethod
    def _collect_returned_days(
        snapshots_by_person: dict[str, FlowPoints],
    ) -> list[tuple[str, FlowPointPeriod, FlowPointDay]]:
        returned_days = []
        seen_dates: set[tuple[str, object]] = set()

        for person_id, snapshot in snapshots_by_person.items():
            for period in snapshot.periods:
                if period.start_date > period.end_date:
                    raise FlowPointLoadError(
                        f"Período inválido para pessoa Flow {person_id}"
                    )
                for day in period.days:
                    if not (
                        period.start_date
                        <= day.work_date
                        <= period.end_date
                    ):
                        raise FlowPointLoadError(
                            "Dia fora do período para pessoa Flow "
                            f"{person_id}: {day.work_date}"
                        )
                    key = (person_id, day.work_date)
                    if key in seen_dates:
                        raise FlowPointLoadError(
                            "Dia duplicado entre períodos para pessoa Flow "
                            f"{person_id}: {day.work_date}"
                        )
                    if any(
                        marked_at.tzinfo is None
                        for marked_at in day.moments
                    ):
                        raise FlowPointLoadError(
                            "Marcação sem fuso horário para pessoa Flow "
                            f"{person_id}: {day.work_date}"
                        )
                    for mark_index in range(0, len(day.moments) - 1, 2):
                        if (
                            day.moments[mark_index + 1]
                            < day.moments[mark_index]
                        ):
                            raise FlowPointLoadError(
                                "Par de marcações em ordem inválida para "
                                f"pessoa Flow {person_id}: {day.work_date}"
                            )
                    seen_dates.add(key)
                    returned_days.append((person_id, period, day))

        return returned_days

    @staticmethod
    def _daily_row(
        person_id: str,
        period: FlowPointPeriod,
        day: FlowPointDay,
        collected_at: datetime,
    ) -> FatoFlowDia:
        return FatoFlowDia(
            flow_person_id=person_id,
            work_date=day.work_date,
            period_start=period.start_date,
            period_end=period.end_date,
            max_availability_date=period.max_availability_date,
            day_starts_at=day.day_starts_at,
            kind=day.kind,
            confirmed=day.confirmed,
            pending_calculation=day.pending_calculation,
            expected_workload=day.expected_workload,
            errors=list(day.errors),
            warnings=list(day.warnings),
            collected_at=collected_at,
        )


class FlowPointService:
    """Fetch and persist points for every active, mapped Flow person."""

    def __init__(
        self,
        client: FlowClient | None = None,
        session_factory: Callable[[], Session] | None = None,
        include_unmapped: bool = False,
    ):
        self._client = client
        self._session_factory = session_factory
        self._include_unmapped = include_unmapped

    def run(self, collected_at: datetime | None = None) -> dict[str, int]:
        client = self._client or FlowClient()
        owns_client = self._client is None
        session_factory = self._session_factory
        if session_factory is None:
            from database.connection import SessionLocal

            session_factory = SessionLocal

        session = session_factory()
        try:
            people_query = select(DimFlowPessoa.flow_person_id).where(
                DimFlowPessoa.is_active.is_(True),
            )
            if not self._include_unmapped:
                people_query = people_query.where(
                    DimFlowPessoa.mapping_status == "mapped",
                )
            person_ids = list(
                session.scalars(
                    people_query.order_by(DimFlowPessoa.flow_person_id)
                )
            )
            snapshots = [
                client.get_points(person_id)
                for person_id in person_ids
            ]
            result = FlowPointLoadService().replace_returned_days(
                session,
                snapshots,
                collected_at=collected_at,
                allow_unmapped=self._include_unmapped,
            )
            session.commit()
            return {
                "people_requested": len(person_ids),
                **result,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if owns_client:
                client.close()
