"""Local operational controls for the productivity ETL."""

from __future__ import annotations

from typing import Any


def run_local(*args: Any, **kwargs: Any) -> int:
    """Load the database-dependent runner only when it is executed."""
    from .runner import run_local as _run_local

    return _run_local(*args, **kwargs)

__all__ = ["run_local"]
