from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeClockifyEntryIssue(Base):
    """Issues explicitly identified in a Clockify description or task."""

    __tablename__ = "bridge_clockify_entry_issue"

    entry_id: Mapped[str] = mapped_column(
        ForeignKey("fato_clockify_entry.entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    issue_key: Mapped[str] = mapped_column(
        ForeignKey("dim_ticket_jira.issue_key"), primary_key=True
    )
    extraction_method: Mapped[str] = mapped_column(String(30))
