from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FatoFlowMarcacao(Base):
    """One ordered Flow clock marking assigned to an attendance day."""

    __tablename__ = "fato_flow_marcacao"
    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_person_id", "work_date"],
            [
                "fato_flow_dia.flow_person_id",
                "fato_flow_dia.work_date",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "order_in_day > 0",
            name="ck_fato_flow_marcacao_order",
        ),
        Index(
            "ix_fato_flow_marcacao_work_date",
            "work_date",
        ),
        Index(
            "ix_fato_flow_marcacao_marked_at",
            "marked_at",
        ),
    )

    flow_person_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    order_in_day: Mapped[int] = mapped_column(Integer, primary_key=True)
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
