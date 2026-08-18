"""Command-line interface for the local phase 6 job."""

from __future__ import annotations

import argparse
import json
from typing import Any


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        from .runner import run_local

        return run_local(
            retries=args.retries,
            retry_delay=args.retry_delay,
            run_acceptance=not args.skip_acceptance,
        )

    if args.command == "migrate":
        from .migration import run_migrations

        return run_migrations()

    if args.command == "acceptance":
        from etl.acceptance import write_acceptance_report

        json_path, markdown_path, report = write_acceptance_report()
        print(json_path)
        print(markdown_path)
        print(f"status={report['status']}")
        return 0 if report["status"] != "not_accepted" else 1

    if args.command == "accept-projects":
        from etl.project_acceptance import write_project_acceptance_report

        json_path, markdown_path, report = write_project_acceptance_report()
        print(json_path)
        print(markdown_path)
        print(f"status={report['status']}")
        return 0 if report["status"] == "accepted" else 1

    if args.command == "backfill-estimates":
        from etl.jira import JiraService

        result = JiraService().backfill_original_estimates(
            projects=args.projects or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "backfill-jira-metadata":
        from etl.jira import JiraService

        service = JiraService()
        projects = args.projects or None
        result = {
            "issue_types": service.backfill_issue_types(projects=projects),
            "crossing_flags": service.backfill_crossing_flags(projects=projects),
            "original_estimates": service.backfill_original_estimates(
                projects=projects,
            ),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "backfill-sprint-changelog":
        from etl.jira_sprint_changelog import run_sprint_changelog_etl

        result = run_sprint_changelog_etl(
            incremental=False,
            max_workers=args.max_workers,
            issue_keys=args.issue_keys or None,
            issue_types=tuple(args.issue_types) if args.issue_types else None,
            resume=args.resume,
            projects=tuple(args.projects) if args.projects else None,
        )
        print(json.dumps({"inserted": result}, ensure_ascii=False, indent=2))
        return 0

    if args.command in {"run-projects", "backfill-projects"}:
        from .projects import run_project_pipeline

        report = run_project_pipeline(
            full=args.command == "backfill-projects",
            epic_start_date=args.from_date,
            resume=args.resume,
            projects=args.projects or None,
            max_workers=args.max_workers,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report["status"] == "success" else 1

    if args.command in {"validate-projects", "reconcile-projects"}:
        from .projects import run_project_check

        exit_code, report = run_project_check(
            "validate" if args.command == "validate-projects" else "reconcile"
        )
        _print_report(report, args.json)
        return exit_code

    if args.command == "status":
        from .status import get_status

        report = get_status(args.limit)
        _print_report(report, args.json)
        return 0

    if args.command == "healthcheck":
        from .status import healthcheck

        report = healthcheck()
        _print_report(report, args.json)
        return 0 if report["healthy"] else 1

    parser.error(f"Comando desconhecido: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m operationalization",
        description="Operação local do ETL Jira + Clockify",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="executa ETL e aceite")
    run_parser.add_argument("--retries", type=_non_negative_int, default=0)
    run_parser.add_argument("--retry-delay", type=_non_negative_int, default=10)
    run_parser.add_argument(
        "--skip-acceptance",
        action="store_true",
        help="não executa a validação após a carga",
    )

    subparsers.add_parser(
        "migrate", help="aplica somente as migrations do PostgreSQL"
    )

    subparsers.add_parser(
        "acceptance", help="executa somente o aceite sobre o banco carregado"
    )

    subparsers.add_parser(
        "accept-projects",
        help="executa o aceite específico do portfólio Jira",
    )

    backfill_parser = subparsers.add_parser(
        "backfill-estimates",
        help="carrega o originalEstimate dos tickets Jira já persistidos",
    )
    backfill_parser.add_argument(
        "--projects",
        nargs="+",
        help="projetos Jira; por padrão usa ZGT ZG ZGTN SRE",
    )

    jira_metadata_parser = subparsers.add_parser(
        "backfill-jira-metadata",
        help="atualiza tipo, atravessamento e estimativa dos tickets existentes",
    )
    jira_metadata_parser.add_argument(
        "--projects",
        nargs="+",
        help="projetos Jira; por padrão usa ZGT ZG ZGTN SRE",
    )

    changelog_parser = subparsers.add_parser(
        "backfill-sprint-changelog",
        help="reprocessa o changelog de Sprint de todos os tickets no escopo",
    )
    changelog_parser.add_argument(
        "--max-workers",
        type=_positive_int,
        default=8,
    )
    changelog_parser.add_argument(
        "--issue-types",
        nargs="+",
        help="limita o backfill a tipos Jira (ex.: Epic); por padrão processa todo o escopo",
    )
    changelog_parser.add_argument(
        "--projects",
        nargs="+",
        help="projetos Jira; por padrão usa ZGT ZG ZGTN SRE",
    )
    changelog_parser.add_argument(
        "--issue-keys",
        nargs="+",
        help="lista explícita de issues para auditoria, inclusive filhos antigos",
    )
    changelog_parser.add_argument(
        "--resume",
        action="store_true",
        help="retoma ignorando itens com checkpoint de sucesso",
    )

    for command, help_text in (
        ("run-projects", "executa a atualização incremental do portfólio Jira"),
        ("backfill-projects", "executa o backfill completo do portfólio Jira"),
    ):
        project_parser = subparsers.add_parser(command, help=help_text)
        project_parser.add_argument(
            "--from",
            dest="from_date",
            default="2026-01-01",
            type=_iso_date,
            help="data inicial dos Epics (YYYY-MM-DD)",
        )
        project_parser.add_argument(
            "--projects",
            nargs="+",
            help="projetos Jira; por padrão usa ZGT ZG ZGTN SRE",
        )
        project_parser.add_argument(
            "--max-workers",
            type=_positive_int,
            default=8,
            help="paralelismo do changelog de status",
        )
        project_parser.add_argument(
            "--resume",
            action="store_true",
            help="retoma checkpoints de changelog já concluídos",
        )

    for command, help_text in (
        ("validate-projects", "valida as views e invariantes do portfólio Jira"),
        ("reconcile-projects", "reconcilia dimensões, hierarquia e views do portfólio"),
    ):
        check_parser = subparsers.add_parser(command, help=help_text)
        check_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser(
        "status", help="mostra as últimas execuções registradas"
    )
    status_parser.add_argument("--limit", type=_positive_int, default=10)
    status_parser.add_argument("--json", action="store_true")

    health_parser = subparsers.add_parser(
        "healthcheck", help="verifica conexão e tabelas essenciais"
    )
    health_parser.add_argument("--json", action="store_true")
    return parser


def _print_report(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("deve ser maior ou igual a zero")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("deve ser maior ou igual a um")
    return parsed


def _iso_date(value: str) -> str:
    from datetime import date

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "deve usar o formato YYYY-MM-DD"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
