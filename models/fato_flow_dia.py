from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoFlowDia(Base):
    """Flow attendance-day snapshot and its calculation metadata."""

    __tablename__ = "fato_flow_dia"
    __table_args__ = (
        CheckConstraint(
            "period_start <= period_end",
            name="ck_fato_flow_dia_period",
        ),
        CheckConstraint(
            "work_date BETWEEN period_start AND period_end",
            name="ck_fato_flow_dia_work_date",
        ),
        Index("ix_fato_flow_dia_work_date", "work_date"),
        Index("ix_fato_flow_dia_collected_at", "collected_at"),
    )

    flow_person_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("dim_flow_pessoa.flow_person_id", ondelete="CASCADE"),
        primary_key=True,
    )
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    max_availability_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    day_starts_at: Mapped[Optional[time]] = mapped_column(
        Time,
        nullable=True,
    )
    kind: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pending_calculation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    expected_workload: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
