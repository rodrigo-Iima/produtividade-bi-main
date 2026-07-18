from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimSprint(Base):
    """Canonical Jira sprint dimension used by PostgreSQL queries."""

    __tablename__ = "dim_sprint"

    sprint_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    sprint_name: Mapped[str] = mapped_column(String(200), index=True)

    sprint_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sprint_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sprint_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
