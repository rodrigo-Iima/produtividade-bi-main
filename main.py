"""Application entrypoint for the Jira/Clockify -> PostgreSQL pipeline."""

import sys
from uuid import uuid4

from config.settings import (
    ETL_AUTO_MIGRATE,
    FLOW_ENABLED,
    FLOW_IDENTITY_SYNC_ENABLED,
    FLOW_POINTS_INCLUDE_UNMAPPED,
)
from clients.flow_client import FlowClient
from database.connection import engine
from database.etl_log import EtlRunLogger
from database.schema import ensure_schema
from database.seed import seed_all
from etl.jira import JiraService
from etl.clockify import ClockifyService
from etl.flow_identity import FlowIdentityETL
from etl.flow_points import FlowPointService
from etl.hours_reconciliation import HoursReconciliationService
from etl.jira_sprint_changelog import run_sprint_changelog_etl
from etl.jira_sprint_enrichment import run_sprint_enrichment
from etl.jira_quick_filters import run_jira_quick_filters
from etl.quality import validate_loaded_data


def _run_step(name: str, operation, logger: EtlRunLogger | None = None) -> bool:
    """Run one pipeline step and return whether it completed successfully."""
    if logger:
        _safe_log(logger.start, name)
    try:
        result = operation()
        if logger:
            _safe_log(logger.finish, name, result)
        print(f"[OK] {name}")
        return True
    except Exception as exc:
        if logger:
            _safe_log(logger.fail, name, exc)
        print(f"[ERROR] {name}: {exc}")
        return False


def main() -> int:
    """Run the ETL and always release the SQLAlchemy engine resources."""
    try:
        return _run_pipeline()
    finally:
        # Always close idle and pooled PostgreSQL connections before the
        # process exits, whether the ETL is run by cron, systemd, Docker, or
        # an interactive shell.
        engine.dispose()


def _run_pipeline() -> int:
    print("=" * 60)
    print("STARTING PRODUTIVIDADE ETL RUN")
    print("=" * 60)

    failures: list[str] = []
    run_id = str(uuid4())

    if ETL_AUTO_MIGRATE:
        if not _run_step("Preparação do schema", ensure_schema):
            failures.append("Preparação do schema")
            return _finish_run(failures, None)
    else:
        print("[SKIP] Preparação do schema (ETL_AUTO_MIGRATE=false)")

    logger = EtlRunLogger(run_id)
    _safe_log(logger.start, "pipeline")

    if not _run_step("Carga das dimensões de referência", seed_all, logger):
        failures.append("Carga das dimensões de referência")
        return _finish_run(failures, logger)

    jira_etl = JiraService()
    jira_result: dict = {}

    def run_jira():
        jira_result.update(jira_etl.run(incremental=True) or {})
        return jira_result

    if not _run_step(
        "Extração e carga do Jira",
        run_jira,
        logger,
    ):
        failures.append("Extração e carga do Jira")
        # Changelog, enriquecimento e cruzamento Clockify/Jira dependem do Jira.
        return _finish_run(failures, logger)

    if not _run_step(
        "Extração do changelog de sprint",
        lambda: run_sprint_changelog_etl(
            incremental=True,
            max_workers=8,
            issue_keys=jira_result.get("issue_keys", []),
        ),
        logger,
    ):
        failures.append("Extração do changelog de sprint")
        return _finish_run(failures, logger)

    if not _run_step("Enriquecimento das sprints Jira", run_sprint_enrichment, logger):
        failures.append("Enriquecimento das sprints Jira")
        return _finish_run(failures, logger)

    if not _run_step(
        "Mapeamento Sprint × Squad pelos quick filters Jira",
        run_jira_quick_filters,
        logger,
    ):
        failures.append("Mapeamento Sprint × Squad pelos quick filters Jira")
        return _finish_run(failures, logger)

    # Clockify depende das sprints e tickets carregados acima para construir os
    # relacionamentos de atribuição. A etapa ainda pode falhar sem apagar a
    # carga anterior, mas a execução deve ser reportada como incompleta.
    clockify_etl = ClockifyService()
    if not _run_step(
        "Extração e carga do Clockify",
        lambda: clockify_etl.run(incremental=True),
        logger,
    ):
        failures.append("Extração e carga do Clockify")

    if not failures:
        failures.extend(_run_flow_steps(logger))
    elif FLOW_ENABLED:
        print("[SKIP] Integração Flow (depende da carga do Clockify)")

    if not failures and not _run_step(
        "Validação da carga transformada",
        validate_loaded_data,
        logger,
    ):
        failures.append("Validação da carga transformada")

    return _finish_run(failures, logger)


def _run_flow_steps(logger: EtlRunLogger | None) -> list[str]:
    """Synchronize Flow identities first, then their returned point days."""
    if not FLOW_ENABLED:
        print("[SKIP] Integração Flow (FLOW_ENABLED=false)")
        return []

    flow_client: FlowClient | None = None

    def get_flow_client() -> FlowClient:
        nonlocal flow_client
        if flow_client is None:
            flow_client = FlowClient()
        return flow_client

    def run_identity():
        result = FlowIdentityETL(client=get_flow_client()).run()
        return {
            **result,
            "extracted": result["people"],
            "transformed": result["people"],
            "loaded": result["people"],
        }

    try:
        if FLOW_IDENTITY_SYNC_ENABLED:
            identity_step = "Sincronização de colaboradores Flow"
            if not _run_step(identity_step, run_identity, logger):
                return [identity_step]
        else:
            print(
                "[SKIP] Sincronização de colaboradores Flow "
                "(FLOW_IDENTITY_SYNC_ENABLED=false)"
            )

        def run_points():
            result = FlowPointService(
                client=get_flow_client(),
                include_unmapped=FLOW_POINTS_INCLUDE_UNMAPPED,
            ).run()
            return {
                **result,
                "extracted": result["marks_loaded"],
                "transformed": result["days_replaced"],
                "loaded": (
                    result["days_replaced"]
                    + result["marks_loaded"]
                    + result["intervals_loaded"]
                ),
            }

        point_step = "Extração e carga das marcações Flow"
        if not _run_step(point_step, run_points, logger):
            return [point_step]

        def run_reconciliation():
            result = HoursReconciliationService().run()
            return {
                **result,
                "extracted": result["records_evaluated"],
                "transformed": result["records_evaluated"],
                "loaded": result["created"] + result["updated"],
            }

        reconciliation_step = "Conferência diária Flow × Clockify"
        if not _run_step(
            reconciliation_step,
            run_reconciliation,
            logger,
        ):
            return [reconciliation_step]
        return []
    finally:
        if flow_client is not None:
            flow_client.close()


def _finish_run(failures: list[str], logger: EtlRunLogger | None) -> int:
    if logger:
        if failures:
            _safe_log(
                logger.fail,
                "pipeline",
                RuntimeError("; ".join(failures)),
            )
        else:
            _safe_log(logger.finish, "pipeline")
    print("=" * 60)
    if failures:
        print("ETL RUN FINISHED WITH ERRORS")
        print("Etapas com erro: " + ", ".join(failures))
        print("=" * 60)
        return 1

    print("ETL RUN FINISHED SUCCESSFULLY")
    print("=" * 60)
    return 0


def _safe_log(operation, *args) -> None:
    """Never turn an audit write failure into a data-load failure."""
    try:
        operation(*args)
    except Exception as exc:
        print(f"[ETLLog] Audit write failed: {exc}")


if __name__ == "__main__":
    sys.exit(main())
