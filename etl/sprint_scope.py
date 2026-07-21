"""Shared business rule for the sprints loaded into the analytical model."""

from datetime import datetime, timezone


SPRINT_START_AFTER = datetime(2026, 1, 1, tzinfo=timezone.utc)
ALLOWED_SPRINT_STATES = frozenset({"ACTIVE", "CLOSED"})


def sprint_is_in_scope(
    sprint_start: datetime | None,
    sprint_state: str | None,
    now: datetime | None = None,
) -> bool:
    """Return whether a sprint is active/closed and started by the current time."""
    if sprint_start is None or sprint_state is None:
        return False

    if sprint_start.tzinfo is None:
        sprint_start = sprint_start.replace(tzinfo=timezone.utc)
    else:
        sprint_start = sprint_start.astimezone(timezone.utc)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    return (
        sprint_state.strip().upper() in ALLOWED_SPRINT_STATES
        and SPRINT_START_AFTER <= sprint_start <= current
    )
