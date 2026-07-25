"""Vercel Cron endpoint that refreshes the weekly OKR snapshot."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler

from vercel.headers import set_headers

from config.settings import (
    JIRA_ESTIMATE_FIELD,
    OKR_TIMEZONE,
    OKR_YEAR,
    build_okr_bugs_jql,
    execution_date,
)
from okr.pipeline import result_to_dashboard_payload, run_analysis
from okr.snapshot_store import SnapshotStore


def _authorized(request: BaseHTTPRequestHandler) -> bool:
    secret = os.getenv("CRON_SECRET")
    authorization = request.headers.get("Authorization", "")
    return bool(secret) and hmac.compare_digest(
        authorization,
        f"Bearer {secret}",
    )


def _send_json(
    request: BaseHTTPRequestHandler,
    status_code: int,
    payload: dict[str, object],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request.send_response(status_code)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        set_headers(dict(self.headers.items()))
        if not _authorized(self):
            _send_json(self, 401, {"error": "unauthorized"})
            return

        try:
            as_of_date = execution_date()
            jql = build_okr_bugs_jql(as_of_date)
            result = run_analysis(
                jql=jql,
                target_year=OKR_YEAR,
                timezone_name=OKR_TIMEZONE,
                estimate_field=JIRA_ESTIMATE_FIELD,
                as_of_date=as_of_date,
            )
            payload = result_to_dashboard_payload(
                result,
                jql=jql,
                target_year=OKR_YEAR,
                timezone_name=OKR_TIMEZONE,
                estimate_field=JIRA_ESTIMATE_FIELD,
                as_of_date=as_of_date,
            )
            pathname = SnapshotStore().write(payload, as_of_date=as_of_date)
            _send_json(
                self,
                200,
                {
                    "status": "ok",
                    "snapshot": pathname,
                    "tickets": len(payload["tickets_with_clockify"]),
                    "months": len(payload["monthly"]),
                },
            )
        except Exception as error:  # pragma: no cover - exercised in Vercel logs
            print(f"[cron] ETL failed: {error}")
            _send_json(self, 500, {"error": "etl_failed"})

    def do_POST(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[cron] {format % args}")
