"""Local job runner for the phase 6 operationalization baseline."""

from __future__ import annotations

import time
from typing import Callable

from etl.acceptance import write_acceptance_report

from .lock import LocalRunLock


def run_local(
    retries: int = 0,
    retry_delay: int = 10,
    run_acceptance: bool = True,
    etl_operation: Callable[[], int] | None = None,
) -> int:
    """Run the ETL once locally, optionally retrying and accepting the load.

    ``etl_operation`` exists to keep retry/lock behavior testable without
    calling the APIs. Normal execution imports and calls ``main.main``.
    """
    if retries < 0:
        raise ValueError("retries deve ser maior ou igual a zero")
    if retry_delay < 0:
        raise ValueError("retry_delay deve ser maior ou igual a zero")

    if etl_operation is None:
        from main import main as etl_operation

    try:
        with LocalRunLock():
            exit_code = _run_with_retries(etl_operation, retries, retry_delay)
            if exit_code != 0 or not run_acceptance:
                return exit_code

            try:
                json_path, markdown_path, report = write_acceptance_report()
            except Exception as exc:
                print(f"[Operationalization] Falha no aceite pós-carga: {exc}")
                return 1

            print(f"[Operationalization] Relatório JSON: {json_path}")
            print(f"[Operationalization] Relatório Markdown: {markdown_path}")
            if report["status"] == "not_accepted":
                print("[Operationalization] Carga não aceita")
                return 1
            if report["status"] == "accepted_with_warnings":
                print("[Operationalization] Carga aceita com avisos")
            else:
                print("[Operationalization] Carga aceita")
            return 0
    except RuntimeError as exc:
        print(f"[Operationalization] {exc}")
        return 2


def _run_with_retries(
    operation: Callable[[], int], retries: int, retry_delay: int
) -> int:
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        print(f"[Operationalization] ETL attempt {attempt}/{attempts}")
        try:
            exit_code = int(operation())
        except Exception as exc:
            print(f"[Operationalization] Exceção não tratada: {exc}")
            exit_code = 1

        if exit_code == 0:
            return 0
        if attempt < attempts:
            print(
                f"[Operationalization] Nova tentativa em {retry_delay} segundos"
            )
            if retry_delay:
                time.sleep(retry_delay)
    return exit_code
