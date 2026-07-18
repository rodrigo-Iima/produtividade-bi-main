from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeClockifyEntrySprint(Base):
    """Sprint attribution result, including unassigned entries."""

    __tablename__ = "bridge_clockify_entry_sprint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("fato_clockify_entry.entry_id", ondelete="CASCADE"),
        index=True,
    )
    sprint_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_sprint.sprint_id"), nullable=True, index=True
    )
    assignment_status: Mapped[str] = mapped_column(String(30), index=True)
    assignment_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
