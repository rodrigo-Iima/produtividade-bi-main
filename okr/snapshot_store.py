"""Vercel Blob persistence for the hosted OKR snapshots."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from vercel.blob import BlobClient, list_objects


SNAPSHOT_PREFIX = "okr/snapshots/"


class SnapshotStore:
    """Store dated dashboard snapshots in a private Vercel Blob store."""

    def __init__(self) -> None:
        self.client = BlobClient()

    def write(self, payload: dict[str, Any], *, as_of_date: date) -> str:
        pathname = f"{SNAPSHOT_PREFIX}{as_of_date.isoformat()}.json"
        self.client.put(
            pathname,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            access="private",
            content_type="application/json",
            overwrite=True,
            cache_control_max_age=60,
        )
        return pathname

    def read_latest(self) -> dict[str, Any] | None:
        listing = list_objects(prefix=SNAPSHOT_PREFIX, limit=1000)
        if not listing.blobs:
            return None

        latest = max(listing.blobs, key=lambda blob: blob.pathname)
        result = self.client.get(
            latest.pathname,
            access="private",
            use_cache=False,
        )
        if result is None or result.status_code != 200 or result.stream is None:
            return None
        content = b"".join(result.stream)
        return json.loads(content.decode("utf-8"))
