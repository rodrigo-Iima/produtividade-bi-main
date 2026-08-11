from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimTicketJira(Base):
    """One current row per Jira ticket."""

    __tablename__ = "dim_ticket_jira"

    issue_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    summary: Mapped[str] = mapped_column(String)
    status_original: Mapped[str] = mapped_column(String(100), index=True)
    project_key: Mapped[str] = mapped_column(String(20), index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    issue_type_id: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True
    )
    issue_type_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    # Jira REST exposes this value in seconds (usually as
    # ``fields.timetracking.originalEstimateSeconds``). Keep the source unit
    # in the dimension so analytical views can derive hours without losing
    # precision or conflating an unset estimate with zero.
    original_estimate_seconds: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    squad_jira: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    atravessamento_flag: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
