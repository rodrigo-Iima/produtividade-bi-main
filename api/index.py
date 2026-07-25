"""Default Python entrypoint for the Vercel project.

The dedicated endpoints remain available at ``/api/cron`` and
``/api/snapshot``. The default ``/api`` route serves the latest snapshot as
well, which gives Vercel a conventional Python entrypoint during detection.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from api.cron import run_cron
from okr.snapshot_store import SnapshotStore


VIEW_ROOT = Path(__file__).resolve().parent.parent / "view"
VIEW_ASSETS = {
    "/view/": ("index.html", "text/html; charset=utf-8"),
    "/view/index.html": ("index.html", "text/html; charset=utf-8"),
    "/view/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/view/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


def _serve_view_asset(
    request: BaseHTTPRequestHandler,
    path: str,
    *,
    send_body: bool = True,
) -> bool:
    if path == "/view":
        request.send_response(307)
        request.send_header("Location", "/view/")
        request.end_headers()
        return True

    asset = VIEW_ASSETS.get(path)
    if asset is None:
        return False

    filename, content_type = asset
    content = (VIEW_ROOT / filename).read_bytes()
    request.send_response(200)
    request.send_header("Content-Type", content_type)
    request.send_header("Cache-Control", "no-store, max-age=0")
    request.send_header("Content-Length", str(len(content)))
    request.end_headers()
    if send_body:
        request.wfile.write(content)
    return True


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        route = parse_qs(parsed_url.query).get("route", [None])[0]
        normalized_path = parsed_url.path.rstrip("/") or "/"

        try:
            if _serve_view_asset(self, parsed_url.path):
                return
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return

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

    def do_HEAD(self) -> None:
        parsed_url = urlsplit(self.path)
        normalized_path = parsed_url.path.rstrip("/") or "/"
        try:
            if _serve_view_asset(self, parsed_url.path, send_body=False):
                return
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(405)
        self.end_headers()

    def do_POST(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[index] {format % args}")
