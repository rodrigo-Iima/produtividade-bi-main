from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class HistConferenciaHorasDia(Base):
    """Audit snapshot written whenever a daily reconciliation changes."""

    __tablename__ = "hist_conferencia_horas_dia"
    __table_args__ = (
        Index(
            "ix_hist_conferencia_horas_user_date",
            "user_id",
            "work_date",
        ),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("dim_colaborador.user_id"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    flow_person_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("dim_flow_pessoa.flow_person_id"),
        nullable=True,
    )
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    flow_covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    flow_day_kind: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    point_day_exists: Mapped[bool] = mapped_column(Boolean, nullable=False)
    point_mark_count: Mapped[int] = mapped_column(Integer, nullable=False)
    point_interval_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    point_worked_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    point_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    clockify_entry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    clockify_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    delta_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tolerance_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    within_tolerance: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adjustment_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    point_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
