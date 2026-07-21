from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeSprintSquad(Base):
    """Many-to-many mapping between a shared Jira sprint and its squads."""

    __tablename__ = "bridge_sprint_squad"
    __table_args__ = (
        PrimaryKeyConstraint("sprint_id", "squad_id"),
        ForeignKeyConstraint(
            ["board_id", "quick_filter_id"],
            [
                "dim_jira_quick_filter.board_id",
                "dim_jira_quick_filter.quick_filter_id",
            ],
        ),
    )

    sprint_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_sprint.sprint_id", ondelete="CASCADE")
    )
    squad_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_squad.squad_id"), index=True
    )
    board_id: Mapped[int] = mapped_column(BigInteger)
    # Boards with a single Squad may be the authoritative source even when
    # they do not expose a Squad quick filter. In that case the bridge keeps
    # the board and leaves the quick-filter reference empty.
    quick_filter_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )
    mapping_source: Mapped[str] = mapped_column(String(50), nullable=False)
    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
