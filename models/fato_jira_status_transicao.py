from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoJiraStatusTransicao(Base):
    """Immutable-ish Jira status transition history at event grain."""

    __tablename__ = "fato_jira_status_transicao"

    transition_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    issue_key: Mapped[str] = mapped_column(String(30))
    # Stable source key generated from Jira changelog metadata. It makes a
    # reload idempotent even when the worker is interrupted after a batch.
    transition_key: Mapped[str] = mapped_column(String(255), nullable=False)
    transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    from_status_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    from_status_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    to_status_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    to_status_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    author_account_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    author_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    source_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
