from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimFlowPessoa(Base):
    """Flow person identity and its optional Clockify collaborator mapping."""

    __tablename__ = "dim_flow_pessoa"
    __table_args__ = (
        CheckConstraint(
            "mapping_status IN ("
            "'mapped', "
            "'unmapped_no_email', "
            "'unmapped_no_match', "
            "'ambiguous_email'"
            ")",
            name="ck_dim_flow_pessoa_mapping_status",
        ),
        CheckConstraint(
            "mapping_method IS NULL OR mapping_method IN ("
            "'corporate_email', 'email', 'manual'"
            ")",
            name="ck_dim_flow_pessoa_mapping_method",
        ),
        CheckConstraint(
            "("
            "mapping_status = 'mapped' "
            "AND clockify_user_id IS NOT NULL "
            "AND mapping_method IS NOT NULL"
            ") OR ("
            "mapping_status <> 'mapped' "
            "AND clockify_user_id IS NULL "
            "AND mapping_method IS NULL"
            ")",
            name="ck_dim_flow_pessoa_mapping_consistency",
        ),
    )

    flow_person_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(200))
    social_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    corporate_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    clockify_user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("dim_colaborador.user_id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    mapping_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'unmapped_no_match'"),
        index=True,
    )
    mapping_method: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
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
