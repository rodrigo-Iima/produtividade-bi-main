from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoClockifyEntry(Base):
    """One canonical row per completed Clockify time entry."""

    __tablename__ = "fato_clockify_entry"

    entry_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("dim_colaborador.user_id"), index=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    project_name: Mapped[str] = mapped_column(String(200))
    task_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    task_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    duration_seconds: Mapped[int] = mapped_column(BigInteger)
