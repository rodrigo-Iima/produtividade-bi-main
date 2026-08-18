from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, String, text
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
    # Portfolio hierarchy and planning dates. Jira can expose the direct
    # parent through either ``parent`` or the legacy Epic Link field; the ETL
    # resolves the relationship into bridge_jira_issue_parent while retaining
    # the direct key here for the common case.
    parent_issue_key: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True
    )
    planned_start_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
    due_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
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
    # ``source_present`` is deliberately independent from the current Jira
    # query result. A ticket that disappears from the source remains auditable
    # and is marked absent by the reconciliation stage instead of being
    # deleted from the warehouse.
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    source_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
