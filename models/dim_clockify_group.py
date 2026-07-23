from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimClockifyGroup(Base):
    """Clockify user group catalog, including capacity groups."""

    __tablename__ = "dim_clockify_group"

    group_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    group_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    capacity_hours_week: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'clockify'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
