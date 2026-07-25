"""CLI for the Jira/Clockify OKR analysis."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Permite executar `python scripts/run_pipeline.py` a partir da raiz do projeto.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    JIRA_ESTIMATE_FIELD,
    OKR_TIMEZONE,
    OKR_YEAR,
    build_okr_bugs_jql,
    execution_date,
)
from okr.pipeline import (
    fetch_inputs,
    raw_inputs_to_payload,
    result_to_payload,
    run_analysis,
    write_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relaciona Bugs Jira de 2026 com horas lançadas no Clockify."
    )
    parser.add_argument("--year", type=int, default=OKR_YEAR)
    parser.add_argument("--jql", help="sobrescreve a JQL padrão")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="busca os dados brutos sem interpretar a estimativa Jira",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="data de corte YYYY-MM-DD; por padrão usa a data da execução",
    )
    args = parser.parse_args()

    as_of_date = args.as_of or execution_date()
    effective_jql = args.jql or build_okr_bugs_jql(as_of_date)

    if args.fetch_only:
        inputs = fetch_inputs(
            jql=effective_jql,
            target_year=args.year,
            timezone_name=OKR_TIMEZONE,
            as_of_date=as_of_date,
        )
        payload = raw_inputs_to_payload(inputs, target_year=args.year)
    else:
        result = run_analysis(
            jql=effective_jql,
            target_year=args.year,
            timezone_name=OKR_TIMEZONE,
            estimate_field=JIRA_ESTIMATE_FIELD,
            as_of_date=as_of_date,
        )
        payload = result_to_payload(
            result,
            jql=effective_jql,
            target_year=args.year,
            timezone_name=OKR_TIMEZONE,
            estimate_field=JIRA_ESTIMATE_FIELD,
            as_of_date=as_of_date,
        )

    output = args.output or Path(
        "outputs",
        f"{'inputs' if args.fetch_only else 'okr'}_{as_of_date.isoformat()}.json",
    )
    write_payload(payload, output)
    print(f"Resultado salvo em {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
