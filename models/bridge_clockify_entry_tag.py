from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BridgeClockifyEntryTag(Base):
    """One row per Clockify entry and tag."""

    __tablename__ = "bridge_clockify_entry_tag"

    entry_id: Mapped[str] = mapped_column(
        ForeignKey("fato_clockify_entry.entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("dim_tag.tag_id"), primary_key=True
    )
    foco_flag: Mapped[str] = mapped_column(String(30))
