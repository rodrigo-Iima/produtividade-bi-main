from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeClockifyUserGroup(Base):
    """Current Clockify group membership for a collaborator."""

    __tablename__ = "bridge_clockify_user_group"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("dim_colaborador.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[str] = mapped_column(
        ForeignKey("dim_clockify_group.group_id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
