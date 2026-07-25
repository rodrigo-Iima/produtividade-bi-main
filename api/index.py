"""Default Python entrypoint for the Vercel project.

The dedicated endpoints remain available at ``/api/cron`` and
``/api/snapshot``. The default ``/api`` route serves the latest snapshot as
well, which gives Vercel a conventional Python entrypoint during detection.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from api.cron import run_cron
from okr.snapshot_store import SnapshotStore


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        route = parse_qs(parsed_url.query).get("route", [None])[0]
        normalized_path = parsed_url.path.rstrip("/") or "/"

        if route == "cron" or normalized_path in {"/api/cron", "/api/cron.py"}:
            run_cron(self)
            return

        try:
            payload = SnapshotStore(request_headers=self.headers).read_latest()
            if payload is None:
                self.send_response(404)
                body = {"error": "snapshot_not_found"}
            else:
                self.send_response(200)
                body = payload

            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except Exception as error:  # pragma: no cover - exercised in Vercel logs
            print(f"[index] read failed: {error}")
            body = json.dumps({"error": "snapshot_unavailable"}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[index] {format % args}")
