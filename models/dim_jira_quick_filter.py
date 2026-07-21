from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimJiraQuickFilter(Base):
    """Quick filters collected from a Jira board."""

    __tablename__ = "dim_jira_quick_filter"

    board_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dim_jira_board.board_id", ondelete="CASCADE"),
        primary_key=True,
    )
    quick_filter_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    jql: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
