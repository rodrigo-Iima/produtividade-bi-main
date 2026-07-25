"""Default Python entrypoint for the Vercel project.

The dedicated endpoints remain available at ``/api/cron`` and
``/api/snapshot``. The default ``/api`` route serves the latest snapshot as
well, which gives Vercel a conventional Python entrypoint during detection.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from vercel.headers import set_headers

from okr.snapshot_store import SnapshotStore


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        set_headers(dict(self.headers.items()))
        try:
            payload = SnapshotStore().read_latest()
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

    def log_message(self, format: str, *args: object) -> None:
        print(f"[index] {format % args}")
