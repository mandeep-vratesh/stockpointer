#!/usr/bin/env python3
"""CLI entry point: python main.py [--date YYYY-MM-DD] [--force-download] [--only a,b] [--skip-upload]."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv
from pipeline.runner import LOG_FORMAT, run  # noqa: E402

load_dotenv()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract raw stock attribute data, store in Oracle, publish CSV.")
    parser.add_argument("--date", type=_iso_date, help="run date YYYY-MM-DD (default: today)")
    parser.add_argument("--force-download", action="store_true", help="re-download even if an offline copy exists")
    parser.add_argument("--only", nargs="+", metavar="COLUMN_ID",
                        help="column_ids to run: 'a,b' or 'a b' (PowerShell turns unquoted a,b into two args)")
    parser.add_argument("--skip-upload", action="store_true", help="build the CSV but do not upload it")
    parser.add_argument("--skip-derived", action="store_true", help="do not compute derived (indicator) fields")
    args = parser.parse_args(argv)  # exits with code 2 on bad input

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    only = [c.strip() for chunk in args.only for c in chunk.split(",") if c.strip()] if args.only else None
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    run_date = args.date or date.today()  # the only place today's date is used
    return run(run_date, ROOT, force_download=args.force_download, only=only, skip_upload=args.skip_upload,
               skip_derived=args.skip_derived)


if __name__ == "__main__":
    sys.exit(main())
