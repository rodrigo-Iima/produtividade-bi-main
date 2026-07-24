"""CLI for the Jira/Clockify OKR analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import (
    JIRA_ESTIMATE_FIELD,
    OKR_BUGS_JQL,
    OKR_TIMEZONE,
    OKR_YEAR,
)
from okr.pipeline import result_to_payload, run_analysis, write_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relaciona Bugs Jira de 2026 com horas lançadas no Clockify."
    )
    parser.add_argument("--year", type=int, default=OKR_YEAR)
    parser.add_argument("--jql", default=OKR_BUGS_JQL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_analysis(
        jql=args.jql,
        target_year=args.year,
        timezone_name=OKR_TIMEZONE,
        estimate_field=JIRA_ESTIMATE_FIELD,
    )
    payload = result_to_payload(
        result,
        jql=args.jql,
        target_year=args.year,
        timezone_name=OKR_TIMEZONE,
        estimate_field=JIRA_ESTIMATE_FIELD,
    )

    if args.output:
        write_payload(payload, args.output)
        print(f"Resultado salvo em {args.output}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
