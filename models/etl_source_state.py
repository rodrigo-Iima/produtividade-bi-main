from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EtlSourceState(Base):
    """Independent checkpoint and operational state for each source pipeline."""

    __tablename__ = "etl_source_state"

    source_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(String(80))
    watermark_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    watermark_value: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_record_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'never_run'")
    )
    rows_processed: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
