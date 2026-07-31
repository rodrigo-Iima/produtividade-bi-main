from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


RECONCILIATION_STATUSES = (
    "fora_cobertura_flow",
    "em_andamento",
    "aguardando_ajuste_ponto",
    "pendencia_ponto_vencida",
    "aguardando_lancamento_clockify",
    "pendencia_clockify_vencida",
    "divergente_no_prazo",
    "divergente_vencido",
    "clockify_maior_no_prazo",
    "clockify_maior_vencido",
    "clockify_menor_no_prazo",
    "clockify_menor_vencido",
    "clockify_em_dia_nao_trabalhado",
    "ignorado_regra_negocio",
    "conferido",
    "sem_movimento",
)


class FatoConferenciaHorasDia(Base):
    """Current source of truth for daily point × Clockify reconciliation."""

    __tablename__ = "fato_conferencia_horas_dia"
    __table_args__ = (
        CheckConstraint(
            "point_mark_count >= 0 "
            "AND point_interval_count >= 0 "
            "AND point_worked_seconds >= 0 "
            "AND clockify_entry_count >= 0 "
            "AND clockify_seconds >= 0 "
            "AND tolerance_seconds >= 0",
            name="ck_fato_conferencia_horas_nonnegative",
        ),
        CheckConstraint(
            "reconciliation_status IN ("
            + ", ".join(f"'{status}'" for status in RECONCILIATION_STATUSES)
            + ")",
            name="ck_fato_conferencia_horas_status",
        ),
        Index(
            "ix_fato_conferencia_horas_status",
            "reconciliation_status",
        ),
        Index(
            "ix_fato_conferencia_horas_work_date",
            "work_date",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("dim_colaborador.user_id"),
        primary_key=True,
    )
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    flow_person_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("dim_flow_pessoa.flow_person_id"),
        nullable=True,
    )
    flow_covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    flow_day_kind: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    point_day_exists: Mapped[bool] = mapped_column(Boolean, nullable=False)
    point_mark_count: Mapped[int] = mapped_column(Integer, nullable=False)
    point_interval_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    point_worked_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    point_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    clockify_entry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    clockify_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    delta_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tolerance_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    within_tolerance: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adjustment_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    point_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
