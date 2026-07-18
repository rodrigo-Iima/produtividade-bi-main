"""Application entrypoint for the Jira/Clockify -> PostgreSQL pipeline."""

import sys
from uuid import uuid4

from database.connection import engine
from database.etl_log import EtlRunLogger
from database.schema import ensure_schema
from database.seed import seed_all
from etl.jira import JiraService
from etl.clockify import ClockifyService
from etl.jira_sprint_changelog import run_sprint_changelog_etl
from etl.jira_sprint_enrichment import run_sprint_enrichment
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
        # Railway Cron Jobs must finish cleanly; dispose also closes idle and
        # pooled PostgreSQL connections before the process exits.
        engine.dispose()


def _run_pipeline() -> int:
    print("=" * 60)
    print("STARTING PRODUTIVIDADE ETL RUN")
    print("=" * 60)

    failures: list[str] = []
    run_id = str(uuid4())

    if not _run_step("Preparação do schema", ensure_schema):
        failures.append("Preparação do schema")
        return _finish_run(failures, None)

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

    if not failures and not _run_step(
        "Validação da carga transformada",
        validate_loaded_data,
        logger,
    ):
        failures.append("Validação da carga transformada")

    return _finish_run(failures, logger)


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
