from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class JiraSprintChangelog(Base):
    """Cache table for Jira sprint changelog — tracks sprint assignment history per issue."""

    __tablename__ = "jira_sprint_changelog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    issue_key: Mapped[str] = mapped_column(
        ForeignKey("dim_ticket_jira.issue_key", ondelete="CASCADE"),
        index=True,
    )

    sprint_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_sprint.sprint_id"), index=True, nullable=True
    )

    # Changelog details
    change_type: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Processing metadata
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
