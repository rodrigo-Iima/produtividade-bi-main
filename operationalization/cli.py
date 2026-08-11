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

    if args.command == "backfill-estimates":
        from etl.jira import JiraService

        result = JiraService().backfill_original_estimates(
            projects=args.projects or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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

    backfill_parser = subparsers.add_parser(
        "backfill-estimates",
        help="carrega o originalEstimate dos tickets Jira já persistidos",
    )
    backfill_parser.add_argument(
        "--projects",
        nargs="+",
        help="projetos Jira; por padrão usa ZGT ZG ZGTN SRE",
    )

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


if __name__ == "__main__":
    raise SystemExit(main())
