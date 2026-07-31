from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimFlowContrato(Base):
    """Minimal Flow employment contract data retained by the project."""

    __tablename__ = "dim_flow_contrato"

    flow_contract_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )
    flow_person_id: Mapped[str] = mapped_column(
        ForeignKey(
            "dim_flow_pessoa.flow_person_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    admitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    establishment: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    role: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    function: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    work_post: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    hierarchy_circle: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    sector: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        index=True,
    )
    flow_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
