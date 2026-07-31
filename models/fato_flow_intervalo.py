from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoFlowIntervalo(Base):
    """One canonical worked interval built from a pair of Flow markings."""

    __tablename__ = "fato_flow_intervalo"
    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_person_id", "work_date"],
            [
                "fato_flow_dia.flow_person_id",
                "fato_flow_dia.work_date",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "pair_order > 0",
            name="ck_fato_flow_intervalo_pair",
        ),
        CheckConstraint(
            "exit_mark_order = entry_mark_order + 1",
            name="ck_fato_flow_intervalo_marks",
        ),
        CheckConstraint(
            "ended_at >= started_at",
            name="ck_fato_flow_intervalo_window",
        ),
        CheckConstraint(
            "duration_seconds >= 0",
            name="ck_fato_flow_intervalo_duration",
        ),
        Index("ix_fato_flow_intervalo_work_date", "work_date"),
    )

    flow_person_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    pair_order: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_mark_order: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_mark_order: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    duration_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
