"""Offline-first fetching and grouping of attributes by their resolved offline file."""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from tenacity import Retrying, before_sleep_log, stop_after_attempt, wait_exponential

from .config import Attribute, Settings, render_template, resolve_offline_path

log = logging.getLogger(__name__)


def group_by_path(attributes: list[Attribute], offline_root: Path, run_date: date) -> dict[Path, list[Attribute]]:
    """Group attributes by resolved offline path, preserving config order."""
    groups: dict[Path, list[Attribute]] = {}
    canonical: dict[str, Path] = {}  # normcase(path) -> first spelling seen (Windows is case-insensitive)
    for attr in attributes:
        path = resolve_offline_path(offline_root, attr.offline_path, run_date)
        key = canonical.setdefault(os.path.normcase(str(path)), path)
        groups.setdefault(key, []).append(attr)
    return groups


def is_cached(path: Path) -> bool:
    """True if the offline copy exists and is non-empty."""
    return path.is_file() and path.stat().st_size > 0


def ensure_file(path: Path, attrs: list[Attribute], run_date: date, settings: Settings, force: bool = False) -> bool:
    """Make sure ``path`` exists. Returns True on cache hit, False if it was downloaded.

    The first attribute's ``download_fn``/``download_url`` win; disagreements only log a warning.
    """
    first = attrs[0]
    url = render_template(first.download_url, run_date)
    for other in attrs[1:]:
        if other.download_fn != first.download_fn or render_template(other.download_url, run_date) != url:
            log.warning("Group %s: %s disagrees with %s on download_fn/download_url; using the latter",
                        path.name, other.column_id, first.column_id)
    if not force and is_cached(path):
        return True
    _download(first, url, path, run_date, settings)
    return False


def _download(attr: Attribute, url: str, path: Path, run_date: date, settings: Settings) -> None:
    """Download to ``<path>.part`` with retries; atomically rename once non-empty."""
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)

    def attempt() -> None:
        part.unlink(missing_ok=True)
        attr.download(url, str(part), run_date, settings)
        if not part.is_file() or part.stat().st_size == 0:
            raise RuntimeError("downloader produced a missing or empty file")
        os.replace(part, path)

    retryer = Retrying(
        stop=stop_after_attempt(settings.download.max_retries + 1),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    try:
        retryer(attempt)
    finally:
        part.unlink(missing_ok=True)
