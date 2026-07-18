from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.dim_ticket_jira import DimTicketJira
from models.fato_clockify_entry import FatoClockifyEntry


class JiraRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_last_updated(self) -> Optional[datetime]:
        """Get the most recent Jira update timestamp for incremental extraction."""
        result = (
            self.session.query(DimTicketJira.updated_at)
            .order_by(DimTicketJira.updated_at.desc())
            .first()
        )
        return result[0] if result else None


class ClockifyRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_last_date(self) -> Optional[date]:
        """Get the most recent Clockify entry date for incremental extraction."""
        result = (
            self.session.query(FatoClockifyEntry.entry_date)
            .order_by(FatoClockifyEntry.entry_date.desc())
            .first()
        )
        return result[0] if result else None
