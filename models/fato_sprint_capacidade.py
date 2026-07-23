from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoSprintCapacidade(Base):
    """Theoretical capacity snapshot at collaborator × Sprint grain."""

    __tablename__ = "fato_sprint_capacidade"

    sprint_id: Mapped[int] = mapped_column(
        ForeignKey("dim_sprint.sprint_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("dim_colaborador.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    squad_id: Mapped[int] = mapped_column(
        ForeignKey("dim_squad.squad_id"), index=True
    )
    squad_name: Mapped[str] = mapped_column(String(200), index=True)
    papel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capacity_group_id: Mapped[str] = mapped_column(
        ForeignKey("dim_clockify_group.group_id"), index=True
    )
    capacity_group_name: Mapped[str] = mapped_column(String(200))
    capacity_hours_week: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    sprint_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sprint_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_days: Mapped[int] = mapped_column(Integer)
    capacity_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'clockify_current_configuration'")
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
