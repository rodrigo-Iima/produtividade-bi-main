"""Pure helpers for interpreting the Jira status history.

The changelog loader persists every transition.  These helpers intentionally
do not collapse a reopen: the complete event stream remains available for
audit, while callers can derive the first execution start and the latest
completion event for a ticket.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
import unicodedata


# Business rule confirmed for the project portfolio: execution starts only
# when an issue enters "Em andamento". "Travado" remains an active bucket,
# but does not establish the real start date.
DEFAULT_EXECUTION_STATUSES = frozenset({"em andamento"})
DEFAULT_COMPLETION_STATUSES = frozenset({
    "concluido",
    "invalido",
    "enviado para evolucao",
    "showcase",
})


def normalize_status_name(value: str | None) -> str:
    """Normalize a Jira status name for a safe business-rule fallback."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return " ".join(normalized.casefold().split())


def _mapping_for(
    transition: Mapping,
    target: str,
    mappings: Mapping | None,
) -> Mapping | None:
    if not mappings:
        return None
    status_id = transition.get(f"{target}_status_id")
    status_name = transition.get(f"{target}_status_name")
    for key in (status_id, status_name, normalize_status_name(status_name)):
        if key and key in mappings:
            return mappings[key]
    return None


def status_starts_execution(
    transition: Mapping,
    mappings: Mapping | None = None,
) -> bool:
    """Return whether a transition enters the confirmed start status."""
    return normalize_status_name(transition.get("to_status_name")) in DEFAULT_EXECUTION_STATUSES


def status_is_completion(
    transition: Mapping,
    mappings: Mapping | None = None,
) -> bool:
    """Return whether a transition enters a completion status."""
    mapping = _mapping_for(transition, "to", mappings)
    if mapping is not None:
        return bool(mapping.get("is_completion"))
    return normalize_status_name(transition.get("to_status_name")) in DEFAULT_COMPLETION_STATUSES


def real_start_at(
    transitions: Iterable[Mapping],
    mappings: Mapping | None = None,
) -> datetime | None:
    """First transition into an execution status."""
    ordered = sorted(
        transitions,
        key=lambda item: item.get("transition_at") or datetime.min,
    )
    for transition in ordered:
        if status_starts_execution(transition, mappings):
            return transition.get("transition_at")
    return None


def real_end_at(
    transitions: Iterable[Mapping],
    resolution_at: datetime | None = None,
    mappings: Mapping | None = None,
) -> datetime | None:
    """Use Jira resolution date, falling back to the latest completion event.

    Reopen events are not discarded.  A downstream view can compare this
    value with later transitions to identify a reopened ticket.
    """
    ordered = sorted(
        transitions,
        key=lambda item: item.get("transition_at") or datetime.min,
    )
    if ordered and not status_is_completion(ordered[-1], mappings):
        # A later transition (typically a reopen) means the ticket no longer
        # has a terminal end. The resolution date is deliberately ignored in
        # this case; earlier completion events remain persisted and can be
        # reported separately without incorrectly stopping active duration at
        # the old completion.
        return None
    if resolution_at is not None:
        return resolution_at
    if not ordered:
        return None
    return ordered[-1].get("transition_at")
