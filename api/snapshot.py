"""Vercel API endpoint that serves the latest hosted snapshot."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from vercel.headers import set_headers

from okr.snapshot_store import SnapshotStore


def _send_json(
    request: BaseHTTPRequestHandler,
    status_code: int,
    payload: dict[str, object],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request.send_response(status_code)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Cache-Control", "no-store, max-age=0")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        set_headers(dict(self.headers.items()))
        try:
            payload = SnapshotStore().read_latest()
            if payload is None:
                _send_json(self, 404, {"error": "snapshot_not_found"})
                return

            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as error:  # pragma: no cover - exercised in Vercel logs
            print(f"[snapshot] read failed: {error}")
            _send_json(self, 500, {"error": "snapshot_unavailable"})

    def log_message(self, format: str, *args: object) -> None:
        print(f"[snapshot] {format % args}")
