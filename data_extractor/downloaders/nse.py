"""Example exchange-specific downloader (shared by several attributes -> one file per date)."""
from __future__ import annotations

from datetime import date

from pipeline.config import Settings

from .generic import http_download

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-extract/1.0)", "Accept": "text/csv,*/*"}


def download_bhavcopy(url: str, dest_path: str, run_date: date, settings: Settings) -> None:
    """Download a daily bhavcopy CSV. Some exchanges need browser-like headers (or cookies) -- add them here."""
    http_download(url, dest_path, run_date, settings, headers=_HEADERS)
