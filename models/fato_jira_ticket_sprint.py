from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoJiraTicketSprint(Base):
    """Historical relationship between a Jira ticket and a sprint."""

    __tablename__ = "fato_jira_ticket_sprint"

    issue_key: Mapped[str] = mapped_column(
        ForeignKey("dim_ticket_jira.issue_key", ondelete="CASCADE"),
        primary_key=True,
    )
    sprint_id: Mapped[int] = mapped_column(
        ForeignKey("dim_sprint.sprint_id"), primary_key=True
    )
    sprint_entrada_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planejado_no_inicio: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
