"""Operational commands for the Jira project portfolio pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Callable, Iterable

from sqlalchemy import text

from database.connection import engine
from database.etl_log import EtlRunLogger
from etl.jira_hierarchy import (
    DEFAULT_EPIC_START_DATE,
    DEFAULT_PROJECTS,
    JiraHierarchyService,
)
from etl.jira_sprint_changelog import run_sprint_changelog_etl
from etl.projects import reconcile_project_data, validate_project_data
from operationalization.lock import PostgresAdvisoryLock


PROJECT_SOURCE_NAME = "jira_projects"
PROJECT_PIPELINE_NAME = "jira_project_portfolio"


def run_project_pipeline(
    *,
    full: bool,
    epic_start_date: str = DEFAULT_EPIC_START_DATE,
    resume: bool = False,
    projects: Iterable[str] | None = None,
    max_workers: int = 8,
    lock_factory: Callable[[], Any] = PostgresAdvisoryLock,
    hierarchy_factory: Callable[[], JiraHierarchyService] = JiraHierarchyService,
    changelog_operation: Callable[..., int] = run_sprint_changelog_etl,
) -> dict[str, Any]:
    """Execute a project-only pipeline under a database advisory lock."""
    project_list = _normalize_projects(projects)
    run_id = str(uuid.uuid4())
    logger = EtlRunLogger(run_id)
    active_step = "pipeline"
    started_at = datetime.now(timezone.utc)

    try:
        with lock_factory():
            logger.start("pipeline")
            _set_source_state(
                status="running",
                last_attempt_at=started_at,
                error_code=None,
                error_message=None,
            )
            try:
                watermark = None if full else _get_watermark()

                active_step = "project_hierarchy"
                logger.start(active_step)
                hierarchy_result = hierarchy_factory().run(
                    projects=project_list,
                    epic_start_date=epic_start_date,
                    updated_since=watermark,
                    # A recurring run reconciles only the changed Epic closure;
                    # the explicit backfill reconciles the complete scope.
                    reconcile_absence=full or watermark is None,
                )
                logger.finish(
                    active_step,
                    _hierarchy_log_counts(hierarchy_result),
                )

                active_step = "project_status_history"
                logger.start(active_step)
                changelog_result = changelog_operation(
                    incremental=not full,
                    max_workers=max_workers,
                    issue_types=("Epic",),
                    resume=resume or not full,
                    projects=tuple(project_list),
                )
                logger.finish(active_step, int(changelog_result))

                active_step = "project_validate"
                logger.start(active_step)
                validation = validate_project_data()
                logger.finish(
                    active_step,
                    {"loaded": validation.get("checks", {}).get("portfolio_rows", 0)},
                )
                if validation.get("status") != "passed":
                    raise RuntimeError(
                        "Validação do portfólio não aprovada: "
                        f"{validation.get('status')}"
                    )

                active_step = "project_reconcile"
                logger.start(active_step)
                reconciliation = reconcile_project_data()
                logger.finish(
                    active_step,
                    {"loaded": reconciliation.get("checks", {}).get("portfolio_rows", 0)},
                )
                if reconciliation.get("status") != "reconciled":
                    raise RuntimeError(
                        "Reconciliação do portfólio não aprovada: "
                        f"{reconciliation.get('status')}"
                    )

                finished_at = datetime.now(timezone.utc)
                _set_source_state(
                    status="success",
                    # Keep the extraction start as the next lower bound. Any
                    # Epic updated while this run is in progress is included
                    # again on the next run instead of being skipped.
                    watermark_at=started_at,
                    last_success_at=finished_at,
                    last_record_at=_get_last_project_record_at(project_list),
                    rows_processed=int(
                        hierarchy_result.get("issues_loaded", 0)
                    ),
                    error_code=None,
                    error_message=None,
                )
                report = {
                    "status": "success",
                    "run_id": run_id,
                    "full": full,
                    "projects": project_list,
                    "watermark_used": watermark,
                    "hierarchy": hierarchy_result,
                    "status_history_rows": int(changelog_result),
                    "validation": validation,
                    "reconciliation": reconciliation,
                }
                logger.finish(
                    "pipeline",
                    {"loaded": hierarchy_result.get("issues_loaded", 0)},
                )
                return report
            except Exception as exc:
                logger.fail(active_step, exc)
                logger.fail("pipeline", exc)
                _set_source_state(
                    status="failed",
                    last_attempt_at=datetime.now(timezone.utc),
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
                return {
                    "status": "failed",
                    "run_id": run_id,
                    "full": full,
                    "projects": project_list,
                    "error": str(exc),
                }
    except Exception as exc:
        # The advisory lock itself can fail before the audit row is created.
        return {
            "status": "locked_or_unavailable",
            "run_id": run_id,
            "full": full,
            "projects": project_list,
            "error": str(exc),
        }


def run_project_check(kind: str) -> tuple[int, dict[str, Any]]:
    """Run a read-only validation/reconciliation with audit logging."""
    if kind not in {"validate", "reconcile"}:
        raise ValueError("kind deve ser validate ou reconcile")
    run_id = str(uuid.uuid4())
    logger = EtlRunLogger(run_id)
    step_name = f"project_{kind}"
    try:
        with PostgresAdvisoryLock():
            logger.start("pipeline")
            logger.start(step_name)
            report = (
                validate_project_data()
                if kind == "validate"
                else reconcile_project_data()
            )
            logger.finish(
                step_name,
                {"loaded": report.get("checks", {}).get("portfolio_rows", 0)},
            )
            logger.finish(
                "pipeline",
                {"loaded": report.get("checks", {}).get("portfolio_rows", 0)},
            )
            report["run_id"] = run_id
            accepted = report.get("status") in {
                "passed",
                "reconciled",
            }
            return (0 if accepted else 1), report
    except Exception as exc:
        try:
            logger.fail(step_name, exc)
            logger.fail("pipeline", exc)
        except Exception:
            pass
        return 2, {
            "status": "failed",
            "run_id": run_id,
            "error": str(exc),
        }


def _normalize_projects(projects: Iterable[str] | None) -> list[str]:
    values = [
        str(project).strip().upper()
        for project in (projects or DEFAULT_PROJECTS)
        if str(project).strip()
    ]
    values = list(dict.fromkeys(values))
    if not values:
        raise ValueError("Informe ao menos um projeto Jira")
    return values


def _hierarchy_log_counts(result: dict[str, Any]) -> dict[str, int]:
    extracted = (
        int(result.get("epics_extracted", 0))
        + int(result.get("children_extracted", 0))
        + int(result.get("subtasks_extracted", 0))
    )
    return {
        "extracted": extracted,
        "transformed": int(result.get("issues_loaded", 0)),
        "loaded": int(result.get("issues_loaded", 0))
        + int(result.get("relations_loaded", 0)),
    }


def _get_watermark() -> datetime | None:
    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT watermark_at FROM public.etl_source_state "
                "WHERE source_name = :source_name"
            ),
            {"source_name": PROJECT_SOURCE_NAME},
        ).scalar_one_or_none()
    return value


def _get_last_project_record_at(projects: Iterable[str]) -> datetime | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT MAX(last_seen_at)
                FROM public.dim_ticket_jira
                WHERE LOWER(TRIM(issue_type_name)) = 'epic'
                  AND project_key = ANY(:projects)
                  AND source_present = TRUE
                """
            ),
            {"projects": list(projects)},
        ).scalar_one_or_none()


def _set_source_state(
    *,
    status: str,
    watermark_at: datetime | None = None,
    last_success_at: datetime | None = None,
    last_attempt_at: datetime | None = None,
    last_record_at: datetime | None = None,
    rows_processed: int | None = None,
    error_code: str | None,
    error_message: str | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO public.etl_source_state(
                    source_name, pipeline_name, watermark_at,
                    last_success_at, last_attempt_at, last_record_at,
                    status, rows_processed, error_code, error_message,
                    updated_at
                ) VALUES (
                    :source_name, :pipeline_name, :watermark_at,
                    :last_success_at, :last_attempt_at, :last_record_at,
                    :status, COALESCE(:rows_processed, 0), :error_code,
                    :error_message, CURRENT_TIMESTAMP
                )
                ON CONFLICT (source_name) DO UPDATE SET
                    pipeline_name = EXCLUDED.pipeline_name,
                    watermark_at = COALESCE(
                        EXCLUDED.watermark_at,
                        etl_source_state.watermark_at
                    ),
                    last_success_at = COALESCE(
                        EXCLUDED.last_success_at,
                        etl_source_state.last_success_at
                    ),
                    last_attempt_at = COALESCE(
                        EXCLUDED.last_attempt_at,
                        etl_source_state.last_attempt_at
                    ),
                    last_record_at = COALESCE(
                        EXCLUDED.last_record_at,
                        etl_source_state.last_record_at
                    ),
                    status = EXCLUDED.status,
                    rows_processed = COALESCE(
                        :rows_processed,
                        etl_source_state.rows_processed
                    ),
                    error_code = :error_code,
                    error_message = :error_message,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "source_name": PROJECT_SOURCE_NAME,
                "pipeline_name": PROJECT_PIPELINE_NAME,
                "watermark_at": watermark_at,
                "last_success_at": last_success_at,
                "last_attempt_at": last_attempt_at,
                "last_record_at": last_record_at,
                "status": status,
                "rows_processed": rows_processed,
                "error_code": error_code,
                "error_message": (error_message or "")[:2000] or None,
            },
        )
