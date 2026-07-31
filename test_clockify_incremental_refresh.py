"""Tests for authoritative Clockify refresh inside the correction window."""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from etl.clockify import ClockifyService
from models.base import Base
from models.bridge_clockify_entry_issue import BridgeClockifyEntryIssue
from models.bridge_clockify_entry_sprint import BridgeClockifyEntrySprint
from models.bridge_clockify_entry_tag import BridgeClockifyEntryTag
from models.dim_colaborador import DimColaborador
from models.dim_sprint import DimSprint
from models.dim_squad import DimSquad
from models.dim_tag import DimTag
from models.dim_ticket_jira import DimTicketJira
from models.fato_clockify_entry import FatoClockifyEntry


def test_refresh_removes_entries_deleted_inside_window_only():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DimSquad.__table__,
            DimColaborador.__table__,
            DimTag.__table__,
            DimTicketJira.__table__,
            DimSprint.__table__,
            FatoClockifyEntry.__table__,
            BridgeClockifyEntryTag.__table__,
            BridgeClockifyEntryIssue.__table__,
            BridgeClockifyEntrySprint.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(
        DimColaborador(
            user_id="u1",
            name="Pessoa",
            email="pessoa@example.com",
            papel=None,
            squad_id=None,
            is_active=True,
        )
    )
    session.add_all(
        [
            _entry("inside", date(2026, 7, 17)),
            _entry("older", date(2026, 7, 1)),
        ]
    )
    session.commit()

    removed = ClockifyService._replace_entries(
        object(),
        session,
        [],
        [],
        [],
        [],
        datetime(2026, 7, 15, tzinfo=timezone.utc),
        datetime(2026, 7, 25, 23, 59, tzinfo=timezone.utc),
    )
    session.commit()

    assert removed == 1
    assert [
        row.entry_id
        for row in session.query(FatoClockifyEntry).all()
    ] == ["older"]
    session.close()
    engine.dispose()


def _entry(entry_id, work_date):
    started_at = datetime(
        work_date.year,
        work_date.month,
        work_date.day,
        12,
        tzinfo=timezone.utc,
    )
    return FatoClockifyEntry(
        entry_id=entry_id,
        user_id="u1",
        squad_id_at_entry=None,
        squad_name_at_entry=None,
        papel_at_entry=None,
        description=None,
        project_name="Produto",
        task_id=None,
        task_name=None,
        started_at=started_at,
        ended_at=started_at,
        entry_date=work_date,
        entry_date_local=work_date,
        duration_seconds=0,
    )
