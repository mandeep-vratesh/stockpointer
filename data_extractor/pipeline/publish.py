"""Build the raw-data CSV from Oracle and upload it to Firebase Storage."""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, storage

from . import oracle
from .config import Attribute, Settings

log = logging.getLogger(__name__)


class PublishError(Exception):
    """Report could not be built or uploaded (exit code 3)."""


def build_csv(conn, attributes: list[Attribute], run_date: date, settings: Settings) -> Path:
    """Query Oracle for ``run_date`` and write ``stock_data_{date}.csv`` (raw values only)."""
    df = oracle.fetch_report(conn, attributes, run_date, settings)
    if df.empty:
        raise PublishError(f"No rows in Oracle for {run_date}; nothing to publish")
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    path = settings.report_dir / f"stock_data_{run_date:%Y-%m-%d}.csv"
    df.to_csv(path, index=False, encoding="utf-8", na_rep="", lineterminator="\n")
    log.info("Report has %d rows x %d columns", len(df), df.shape[1])
    return path


def upload_csv(csv_path: Path, run_date: date, settings: Settings) -> str:
    """Upload the CSV (private, overwriting) and return its ``gs://`` URI."""
    fb = settings.firebase
    cred_file = os.environ.get(fb.credentials_env)
    bucket = os.environ.get(fb.bucket)
    if not bucket:
        raise PublishError(f"Environment variable {fb.bucket} is not set")
    if not cred_file:
        raise PublishError(f"Environment variable {fb.credentials_env} is not set")
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(credentials.Certificate(cred_file), {"storageBucket": bucket})

    day = f"{run_date:%Y-%m-%d}"
    object_name = "/".join(p for p in (fb.report_prefix.strip("/"), day, f"stock_data_{day}.csv") if p)
    blob = storage.bucket().blob(object_name)
    blob.upload_from_filename(str(csv_path), content_type="text/csv")  # not made public
    return f"gs://{blob.bucket.name}/{blob.name}"
