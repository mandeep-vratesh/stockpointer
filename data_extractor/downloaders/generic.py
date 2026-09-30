"""Generic HTTP downloader."""
from __future__ import annotations

from datetime import date

import requests

from pipeline.config import Settings


def http_download(url: str, dest_path: str, run_date: date, settings: Settings,
                  headers: dict[str, str] | None = None,
                  session: requests.Session | None = None) -> None:
    """Stream ``url`` to ``dest_path``; raises on HTTP errors or timeouts."""
    getter = session.get if session else requests.get
    with getter(url, stream=True, timeout=settings.download.timeout_seconds, headers=headers) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fh.write(chunk)
