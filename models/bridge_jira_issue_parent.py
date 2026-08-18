from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeJiraIssueParent(Base):
    """Current Jira hierarchy edges, stored as child -> parent."""

    __tablename__ = "bridge_jira_issue_parent"

    child_issue_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    parent_issue_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    source_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
