"""Tests for transactional and idempotent Flow point loading."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clients.flow_dto import FlowPoints
from etl.flow_points import (
    FlowPointLoadError,
    FlowPointLoadService,
    FlowPointService,
)
from models.base import Base
from models.dim_colaborador import DimColaborador
from models.dim_flow_pessoa import DimFlowPessoa
from models.dim_squad import DimSquad
from models.fato_flow_dia import FatoFlowDia
from models.fato_flow_intervalo import FatoFlowIntervalo
from models.fato_flow_marcacao import FatoFlowMarcacao


COLLECTED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DimSquad.__table__,
            DimColaborador.__table__,
            DimFlowPessoa.__table__,
            FatoFlowDia.__table__,
            FatoFlowMarcacao.__table__,
            FatoFlowIntervalo.__table__,
        ],
    )
    local_session_factory = sessionmaker(bind=engine)
    session = local_session_factory()
    try:
        yield session, local_session_factory
    finally:
        session.close()
        engine.dispose()


def _add_person(
    session,
    person_id="p1",
    user_id="u1",
    *,
    mapped=True,
    active=True,
):
    session.add(
        DimColaborador(
            user_id=user_id,
            name=f"Clockify {user_id}",
            email=f"{user_id}@example.com",
            papel=None,
            squad_id=None,
            is_active=True,
        )
    )
    session.add(
        DimFlowPessoa(
            flow_person_id=person_id,
            name=f"Flow {person_id}",
            social_name=None,
            corporate_email=f"{user_id}@example.com",
            email=None,
            clockify_user_id=user_id if mapped else None,
            mapping_status="mapped" if mapped else "unmapped_no_match",
            mapping_method="corporate_email" if mapped else None,
            is_active=active,
            flow_last_seen_at=COLLECTED_AT,
            updated_at=COLLECTED_AT,
        )
    )
    session.flush()


def _snapshot(person_id="p1", days=None):
    days = days or []
    return FlowPoints.from_api(
        person_id,
        {
            "periods": [
                {
                    "start_date": "2026-07-16",
                    "end_date": "2026-08-15",
                    "max_availability_date": "2026-07-29",
                    "masters": days,
                }
            ]
        },
    )


def _day(
    work_date,
    moments,
    *,
    errors=None,
    warnings=None,
    confirmed=True,
):
    return {
        "master_date": work_date,
        "day_starts_at": "00:00:00",
        "kind": "WORKING_DAY",
        "confirmed": confirmed,
        "pending_calculation": False,
        "default_moments": "08:00",
        "moments": moments,
        "errors": errors or [],
        "warnings": warnings or [],
    }


def _marks(session, work_date):
    if isinstance(work_date, str):
        work_date = date.fromisoformat(work_date)
    return (
        session.query(FatoFlowMarcacao)
        .filter(FatoFlowMarcacao.work_date == work_date)
        .order_by(FatoFlowMarcacao.order_in_day)
        .all()
    )


def test_initial_load_persists_daily_metadata_and_ordered_marks(database):
    session, _factory = database
    _add_person(session)

    result = FlowPointLoadService().replace_returned_days(
        session,
        [
            _snapshot(
                days=[
                    _day(
                        "2026-07-28",
                        [
                            "2026-07-28 08:03:00",
                            "2026-07-28 12:01:00",
                            "2026-07-28 13:02:00",
                            "2026-07-28 18:04:00",
                        ],
                        warnings=["Aguardando confirmação"],
                    ),
                    _day(
                        "2026-07-29",
                        ["2026-07-29 08:00:00"],
                        errors=["Marcações ímpares"],
                        confirmed=False,
                    ),
                ]
            )
        ],
        collected_at=COLLECTED_AT,
    )

    assert result == {
        "people_received": 1,
        "people_with_returned_days": 1,
        "days_replaced": 2,
        "marks_loaded": 5,
        "intervals_loaded": 2,
    }
    first_day = session.get(
        FatoFlowDia,
        ("p1", date(2026, 7, 28)),
    )
    assert first_day.period_start.isoformat() == "2026-07-16"
    assert first_day.max_availability_date.isoformat() == "2026-07-29"
    assert first_day.warnings == ["Aguardando confirmação"]
    assert [
        row.order_in_day for row in _marks(session, "2026-07-28")
    ] == [1, 2, 3, 4]
    assert (
        session.query(FatoFlowIntervalo)
        .filter(FatoFlowIntervalo.work_date == date(2026, 7, 28))
        .count()
        == 2
    )


def test_rerun_is_idempotent_and_replaces_only_returned_dates(database):
    session, _factory = database
    _add_person(session)
    loader = FlowPointLoadService()
    initial = _snapshot(
        days=[
            _day(
                "2026-07-27",
                [
                    "2026-07-27 08:00:00",
                    "2026-07-27 18:00:00",
                ],
            ),
            _day(
                "2026-07-28",
                [
                    "2026-07-28 08:00:00",
                    "2026-07-28 18:00:00",
                ],
            ),
        ]
    )

    loader.replace_returned_days(session, [initial], COLLECTED_AT)
    loader.replace_returned_days(session, [initial], COLLECTED_AT)
    assert session.query(FatoFlowDia).count() == 2
    assert session.query(FatoFlowMarcacao).count() == 4

    loader.replace_returned_days(
        session,
        [
            _snapshot(
                days=[
                    _day(
                        "2026-07-28",
                        [
                            "2026-07-28 08:15:00",
                            "2026-07-28 12:00:00",
                            "2026-07-28 13:00:00",
                            "2026-07-28 18:05:00",
                        ],
                    )
                ]
            )
        ],
        COLLECTED_AT,
    )

    assert len(_marks(session, "2026-07-27")) == 2
    replaced = _marks(session, "2026-07-28")
    assert len(replaced) == 4
    assert replaced[0].marked_at.hour == 8
    assert replaced[0].marked_at.minute == 15


def test_returned_day_without_moments_clears_previous_marks(database):
    session, _factory = database
    _add_person(session)
    loader = FlowPointLoadService()
    loader.replace_returned_days(
        session,
        [
            _snapshot(
                days=[
                    _day(
                        "2026-07-28",
                        [
                            "2026-07-28 08:00:00",
                            "2026-07-28 18:00:00",
                        ],
                    )
                ]
            )
        ],
        COLLECTED_AT,
    )

    loader.replace_returned_days(
        session,
        [_snapshot(days=[_day("2026-07-28", [])])],
        COLLECTED_AT,
    )

    assert session.get(
        FatoFlowDia,
        ("p1", date(2026, 7, 28)),
    ) is not None
    assert _marks(session, "2026-07-28") == []


def test_overnight_pair_stays_assigned_to_flow_work_date(database):
    session, _factory = database
    _add_person(session)

    FlowPointLoadService().replace_returned_days(
        session,
        [
            _snapshot(
                days=[
                    _day(
                        "2026-07-28",
                        [
                            "2026-07-28 22:00:00",
                            "2026-07-29 02:00:00",
                        ],
                    )
                ]
            )
        ],
        COLLECTED_AT,
    )

    interval = session.query(FatoFlowIntervalo).one()
    assert interval.work_date == date(2026, 7, 28)
    assert interval.duration_seconds == 4 * 60 * 60


def test_invalid_batch_is_rejected_before_existing_data_changes(database):
    session, _factory = database
    _add_person(session)
    loader = FlowPointLoadService()
    loader.replace_returned_days(
        session,
        [
            _snapshot(
                days=[
                    _day(
                        "2026-07-28",
                        [
                            "2026-07-28 08:00:00",
                            "2026-07-28 18:00:00",
                        ],
                    )
                ]
            )
        ],
        COLLECTED_AT,
    )
    invalid = FlowPoints.from_api(
        "p1",
        {
            "periods": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-15",
                    "masters": [_day("2026-07-28", [])],
                }
            ]
        },
    )

    with pytest.raises(FlowPointLoadError, match="Dia fora do período"):
        loader.replace_returned_days(session, [invalid], COLLECTED_AT)

    assert len(_marks(session, "2026-07-28")) == 2


@pytest.mark.parametrize(
    ("mapped", "active"),
    [(False, True), (True, False)],
)
def test_loader_rejects_people_not_active_and_mapped(
    database,
    mapped,
    active,
):
    session, _factory = database
    _add_person(session, mapped=mapped, active=active)

    with pytest.raises(
        FlowPointLoadError,
        match="não está ativa e mapeada",
    ):
        FlowPointLoadService().replace_returned_days(
            session,
            [_snapshot()],
            COLLECTED_AT,
        )


def test_service_requests_only_active_mapped_people(database):
    session, factory = database
    _add_person(session, "p-active", "u-active")
    _add_person(
        session,
        "p-unmapped",
        "u-unmapped",
        mapped=False,
    )
    _add_person(
        session,
        "p-inactive",
        "u-inactive",
        active=False,
    )
    session.commit()
    client = _FakeFlowClient()

    result = FlowPointService(
        client=client,
        session_factory=factory,
    ).run(COLLECTED_AT)

    assert client.requested == ["p-active"]
    assert result == {
        "people_requested": 1,
        "people_received": 1,
        "people_with_returned_days": 1,
        "days_replaced": 1,
        "marks_loaded": 2,
        "intervals_loaded": 1,
    }
    session.expire_all()
    assert session.query(FatoFlowMarcacao).count() == 2


class _FakeFlowClient:
    def __init__(self):
        self.requested = []

    def get_points(self, person_id):
        self.requested.append(person_id)
        return _snapshot(
            person_id,
            [
                _day(
                    "2026-07-28",
                    [
                        "2026-07-28 08:00:00",
                        "2026-07-28 18:00:00",
                    ],
                )
            ],
        )
