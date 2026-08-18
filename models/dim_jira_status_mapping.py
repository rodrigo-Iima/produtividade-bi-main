from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimJiraStatusMapping(Base):
    """Project-aware business mapping for Jira status semantics."""

    __tablename__ = "dim_jira_status_mapping"

    # ``*`` is the global fallback. A project-specific row wins over it in
    # downstream views; status_context distinguishes additional business
    # contexts when one Jira status has different meanings by project.
    project_key: Mapped[str] = mapped_column(
        String(20), primary_key=True, server_default=text("'*'")
    )
    status_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status_context: Mapped[str] = mapped_column(
        String(50), primary_key=True, server_default=text("'global'")
    )
    status_name: Mapped[str] = mapped_column(String(200))
    status_group: Mapped[str] = mapped_column(String(50), index=True)
    starts_execution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_completion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'manual'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
