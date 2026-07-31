"""Tests for incremental Flow point × Clockify reconciliation."""

from datetime import date, datetime, timezone
import subprocess
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clients.flow_dto import FlowPoints
from etl.flow_points import FlowPointLoadService
from etl.hours_reconciliation import (
    HoursReconciliationService,
    classify_daily_reconciliation,
    competence_adjustment_deadline,
)
from models.base import Base
from models.dim_colaborador import DimColaborador
from models.dim_flow_pessoa import DimFlowPessoa
from models.dim_squad import DimSquad
from models.fato_clockify_entry import FatoClockifyEntry
from models.fato_conferencia_horas_dia import FatoConferenciaHorasDia
from models.fato_flow_dia import FatoFlowDia
from models.fato_flow_intervalo import FatoFlowIntervalo
from models.fato_flow_marcacao import FatoFlowMarcacao
from models.hist_conferencia_horas_dia import HistConferenciaHorasDia


def test_approved_point_adjustment_updates_truth_and_keeps_history():
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
            FatoClockifyEntry.__table__,
            FatoConferenciaHorasDia.__table__,
            HistConferenciaHorasDia.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    initial_collection = datetime(
        2026,
        7,
        20,
        12,
        0,
        tzinfo=timezone.utc,
    )
    with factory() as session:
        _seed_identity(session, initial_collection)
        session.add(
            FatoClockifyEntry(
                entry_id="clockify-17",
                user_id="u1",
                squad_id_at_entry=None,
                squad_name_at_entry=None,
                papel_at_entry="Desenvolvedor",
                description="Trabalho do dia",
                project_name="Produto",
                task_id=None,
                task_name=None,
                started_at=datetime(
                    2026,
                    7,
                    17,
                    11,
                    0,
                    tzinfo=timezone.utc,
                ),
                ended_at=datetime(
                    2026,
                    7,
                    17,
                    19,
                    0,
                    tzinfo=timezone.utc,
                ),
                entry_date=date(2026, 7, 17),
                entry_date_local=date(2026, 7, 17),
                duration_seconds=8 * 60 * 60,
            )
        )
        FlowPointLoadService().replace_returned_days(
            session,
            [_snapshot([], confirmed=False)],
            initial_collection,
        )
        session.commit()

    service = HoursReconciliationService(
        session_factory=factory,
        lookback_days=45,
        competence_closing_day=25,
        ignored_flow_person_ids=frozenset(),
    )
    first = service.run(
        as_of=initial_collection,
        start_date=date(2026, 7, 1),
    )
    assert first["created"] == 1

    with factory() as session:
        current = session.get(
            FatoConferenciaHorasDia,
            ("u1", date(2026, 7, 17)),
        )
        assert current.reconciliation_status == "aguardando_ajuste_ponto"
        assert current.point_worked_seconds == 0
        assert current.clockify_seconds == 8 * 60 * 60
        assert current.adjustment_deadline == date(2026, 7, 25)

        correction_collection = datetime(
            2026,
            7,
            25,
            12,
            0,
            tzinfo=timezone.utc,
        )
        FlowPointLoadService().replace_returned_days(
            session,
            [
                _snapshot(
                    [
                        "2026-07-17 08:00:00",
                        "2026-07-17 12:00:00",
                        "2026-07-17 13:00:00",
                        "2026-07-17 17:00:00",
                    ],
                    confirmed=False,
                )
            ],
            correction_collection,
        )
        session.commit()

    second = service.run(
        as_of=correction_collection,
        start_date=date(2026, 7, 1),
    )
    assert second["updated"] == 1
    assert second["history_written"] == 1

    with factory() as session:
        current = session.get(
            FatoConferenciaHorasDia,
            ("u1", date(2026, 7, 17)),
        )
        assert current.reconciliation_status == "conferido"
        assert current.point_interval_count == 2
        assert current.point_worked_seconds == 8 * 60 * 60
        assert current.delta_seconds == 0
        history = (
            session.query(HistConferenciaHorasDia)
            .order_by(HistConferenciaHorasDia.event_id)
            .all()
        )
        assert [row.reconciliation_status for row in history] == [
            "aguardando_ajuste_ponto",
            "conferido",
        ]

    third = service.run(
        as_of=correction_collection,
        start_date=date(2026, 7, 1),
    )
    assert third["unchanged"] == 1
    assert third["history_written"] == 0
    engine.dispose()


def test_missing_point_becomes_overdue_after_adjustment_deadline():
    status = classify_daily_reconciliation(
        work_date=date(2026, 7, 17),
        as_of_date=date(2026, 7, 26),
        adjustment_deadline=date(2026, 7, 25),
        point_mark_count=0,
        point_complete=False,
        point_worked_seconds=0,
        clockify_entry_count=1,
        clockify_seconds=8 * 60 * 60,
    )

    assert status == "pendencia_ponto_vencida"


def test_competence_closes_on_day_25_of_work_month():
    assert competence_adjustment_deadline(
        date(2026, 7, 17),
        25,
    ) == date(2026, 7, 25)
    assert competence_adjustment_deadline(
        date(2026, 7, 29),
        25,
    ) == date(2026, 7, 25)


def test_ignored_person_does_not_generate_reconciliation_problem():
    status = classify_daily_reconciliation(
        work_date=date(2026, 7, 17),
        as_of_date=date(2026, 7, 30),
        adjustment_deadline=date(2026, 7, 25),
        flow_covered=False,
        point_mark_count=0,
        point_complete=False,
        point_worked_seconds=0,
        clockify_entry_count=1,
        clockify_seconds=6 * 60 * 60,
        ignored=True,
    )

    assert status == "ignorado_regra_negocio"


def test_clockify_day_outside_returned_flow_period_is_not_overdue():
    status = classify_daily_reconciliation(
        work_date=date(2026, 6, 20),
        as_of_date=date(2026, 7, 30),
        adjustment_deadline=date(2026, 6, 28),
        flow_covered=False,
        point_mark_count=0,
        point_complete=False,
        point_worked_seconds=0,
        clockify_entry_count=1,
        clockify_seconds=8 * 60 * 60,
    )

    assert status == "fora_cobertura_flow"


def test_difference_within_fifteen_minutes_is_reconciled():
    status = classify_daily_reconciliation(
        work_date=date(2026, 7, 17),
        as_of_date=date(2026, 7, 26),
        adjustment_deadline=date(2026, 7, 25),
        point_mark_count=4,
        point_complete=True,
        point_worked_seconds=8 * 60 * 60,
        clockify_entry_count=1,
        clockify_seconds=(8 * 60 * 60) + (15 * 60),
        tolerance_seconds=15 * 60,
    )

    assert status == "conferido"


def test_difference_direction_is_explicit_after_tolerance():
    common = {
        "work_date": date(2026, 7, 17),
        "as_of_date": date(2026, 7, 26),
        "adjustment_deadline": date(2026, 7, 25),
        "point_mark_count": 4,
        "point_complete": True,
        "clockify_entry_count": 1,
        "tolerance_seconds": 15 * 60,
    }

    assert classify_daily_reconciliation(
        **common,
        point_worked_seconds=8 * 60 * 60,
        clockify_seconds=9 * 60 * 60,
    ) == "clockify_maior_vencido"
    assert classify_daily_reconciliation(
        **common,
        point_worked_seconds=8 * 60 * 60,
        clockify_seconds=7 * 60 * 60,
    ) == "clockify_menor_vencido"


def test_clockify_on_vacation_is_flagged():
    status = classify_daily_reconciliation(
        work_date=date(2026, 7, 17),
        as_of_date=date(2026, 7, 18),
        adjustment_deadline=date(2026, 7, 25),
        point_mark_count=0,
        point_complete=False,
        point_worked_seconds=0,
        clockify_entry_count=1,
        clockify_seconds=8 * 60 * 60,
        flow_day_kind="Férias",
        tolerance_seconds=15 * 60,
    )

    assert status == "clockify_em_dia_nao_trabalhado"


def test_clockify_entry_is_split_at_flow_local_midnight():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DimSquad.__table__,
            DimColaborador.__table__,
            FatoClockifyEntry.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            DimColaborador(
                user_id="u1",
                name="Pessoa",
                email="pessoa@example.com",
                papel="Desenvolvedor",
                squad_id=None,
                is_active=True,
            )
        )
        session.add(
            FatoClockifyEntry(
                entry_id="overnight",
                user_id="u1",
                squad_id_at_entry=None,
                squad_name_at_entry=None,
                papel_at_entry="Desenvolvedor",
                description="Virada",
                project_name="Produto",
                task_id=None,
                task_name=None,
                started_at=datetime(
                    2026, 7, 18, 1, 0, tzinfo=timezone.utc
                ),
                ended_at=datetime(
                    2026, 7, 18, 5, 0, tzinfo=timezone.utc
                ),
                entry_date=date(2026, 7, 18),
                entry_date_local=date(2026, 7, 17),
                duration_seconds=4 * 60 * 60,
            )
        )
        session.commit()

        result = HoursReconciliationService._clockify_aggregates(
            session,
            {"u1": "p1"},
            date(2026, 7, 17),
            date(2026, 7, 18),
        )

    assert result[("u1", date(2026, 7, 17))].seconds == 2 * 60 * 60
    assert result[("u1", date(2026, 7, 18))].seconds == 2 * 60 * 60
    assert result[("u1", date(2026, 7, 17))].entry_count == 1
    assert result[("u1", date(2026, 7, 18))].entry_count == 1
    engine.dispose()


def test_reconciliation_module_loads_its_orm_dependencies():
    command = (
        "from etl.hours_reconciliation import HoursReconciliationService; "
        "from models.base import Base; "
        "assert 'dim_colaborador' in Base.metadata.tables; "
        "assert 'dim_squad' in Base.metadata.tables"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _seed_identity(session, observed_at):
    session.add(
        DimColaborador(
            user_id="u1",
            name="Pessoa",
            email="pessoa@example.com",
            papel="Desenvolvedor",
            squad_id=None,
            is_active=True,
        )
    )
    session.add(
        DimFlowPessoa(
            flow_person_id="p1",
            name="Pessoa",
            social_name=None,
            corporate_email="pessoa@example.com",
            email=None,
            clockify_user_id="u1",
            mapping_status="mapped",
            mapping_method="corporate_email",
            is_active=True,
            flow_last_seen_at=observed_at,
            updated_at=observed_at,
        )
    )
    session.flush()


def _snapshot(moments, *, confirmed):
    return FlowPoints.from_api(
        "p1",
        {
            "periods": [
                {
                    "start_date": "2026-07-16",
                    "end_date": "2026-08-15",
                    "max_availability_date": "2026-07-25",
                    "masters": [
                        {
                            "master_date": "2026-07-17",
                            "day_starts_at": "00:00:00",
                            "kind": "WORKING_DAY",
                            "confirmed": confirmed,
                            "pending_calculation": False,
                            "default_moments": "08:00",
                            "moments": moments,
                            "errors": [],
                            "warnings": [],
                        }
                    ],
                }
            ]
        },
    )
