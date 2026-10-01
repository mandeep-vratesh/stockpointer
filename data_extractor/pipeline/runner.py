"""Orchestration: validate -> fetch/process groups in parallel -> write Oracle -> derive -> publish."""
from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import fetch, oracle, publish
from .config import (Attribute, Column, ConfigError, DerivedAttribute, Settings, check_env, load_attributes,
                     load_derived, load_settings)

log = logging.getLogger("stock_extract")

EXIT_OK, EXIT_PARTIAL, EXIT_CONFIG, EXIT_FATAL = 0, 1, 2, 3
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


@dataclass
class GroupResult:
    """Outcome of fetching one file and running all its attributes' processors."""
    path: Path
    attributes: list[Attribute]
    cache_hit: bool = False
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)   # column_id -> DataFrame
    errors: dict[str, str] = field(default_factory=dict)            # column_id -> message
    seconds: float = 0.0


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _validate_output(df: object, allow_empty: bool = False) -> pd.DataFrame:
    """Enforce the post_process_fn contract: columns {stock_id, value}, unique non-empty stock IDs."""
    if not isinstance(df, pd.DataFrame):
        raise ValueError(f"expected a DataFrame, got {type(df).__name__}")
    if set(df.columns) != {"stock_id", "value"}:
        raise ValueError(f"columns must be exactly ['stock_id', 'value'], got {list(df.columns)}")
    if df.empty and not allow_empty:
        raise ValueError("processor returned no rows")
    out = df[["stock_id", "value"]].copy()
    if out["stock_id"].isna().any():
        raise ValueError("null stock_id values")
    out["stock_id"] = out["stock_id"].astype(str).str.strip()
    if (out["stock_id"] == "").any():
        raise ValueError("empty stock_id values")
    dups = out["stock_id"][out["stock_id"].duplicated()].unique()
    if len(dups):
        raise ValueError(f"duplicate stock_id values, e.g. {list(dups[:5])}")
    return out.reset_index(drop=True)


def _process_group(path: Path, attrs: list[Attribute], run_date: date, settings: Settings,
                   force: bool) -> GroupResult:
    """Fetch the group's file once, then run each attribute's processor (sequential in a group)."""
    start = time.monotonic()
    res = GroupResult(path, attrs)
    try:
        res.cache_hit = fetch.ensure_file(path, attrs, run_date, settings, force)
    except Exception as exc:  # a failed download fails the whole group
        msg = f"download failed: {_describe(exc)}"
        res.errors = {a.column_id: msg for a in attrs}
    else:
        for a in attrs:
            try:
                res.frames[a.column_id] = _validate_output(a.process(str(path), run_date))
            except Exception as exc:  # a failed processor fails only its attribute
                log.error("%s: processor failed: %s", a.column_id, _describe(exc), exc_info=True)
                res.errors[a.column_id] = f"processing failed: {_describe(exc)}"
    res.seconds = time.monotonic() - start
    status = "CACHE HIT" if res.cache_hit else ("DOWNLOAD FAILED" if not res.frames and res.errors and
                                                  all(m.startswith("download") for m in res.errors.values()) else "DOWNLOAD")
    log.info("GROUP %s | %s | attributes=%s | ok=%d failed=%d | %.2fs", path, status,
             [a.column_id for a in attrs], len(res.frames), len(res.errors), res.seconds)
    return res


def _select(attributes: list[Column], only: list[str] | None) -> list[Column]:
    if not only:
        return attributes
    unknown = sorted(set(only) - {a.column_id for a in attributes})
    if unknown:
        raise ConfigError(f"--only references unknown column_id(s): {unknown}")
    return [a for a in attributes if a.column_id in set(only)]


@dataclass
class Plan:
    """Everything resolved from config for one run."""
    all_columns: list[Column]                 # every raw + derived column (schema check, CSV)
    raw_by_id: dict[str, Attribute]           # all raw attributes (derived fields read them from Oracle)
    raw: list[Attribute]                      # raw attributes selected for this run
    derived: list[DerivedAttribute]           # derived attributes selected for this run
    groups: dict[Path, list[Attribute]]


def _write(conn, columns: list[Column], frames: dict[str, pd.DataFrame], errors: dict[str, str],
           run_date: date, settings: Settings) -> None:
    """One MERGE (one transaction) per table for the columns that have a frame; failures go to ``errors``."""
    by_table: dict[str, list[Column]] = {}
    for c in columns:
        if c.column_id in frames:
            by_table.setdefault(c.oracle_table, []).append(c)
    for table, cols in by_table.items():
        try:
            n = oracle.upsert_table(conn, table, [(c.oracle_column, frames[c.column_id]) for c in cols],
                                    run_date, settings)
            log.info("WRITE %s | %d rows | columns=%s", table, n, [c.oracle_column for c in cols])
        except Exception as exc:
            log.error("WRITE %s failed, rolled back: %s", table, _describe(exc))
            for c in cols:
                errors[c.column_id] = f"write failed: {_describe(exc)}"


def _run_derived(conn, derived: list[DerivedAttribute], raw_by_id: dict[str, Attribute],
                 frames: dict[str, pd.DataFrame], errors: dict[str, str], run_date: date,
                 settings: Settings) -> None:
    """Compute derived fields from Oracle history (read after the raw write has committed).

    Each derived field gets exactly the stocks that have a row on ``run_date`` (NaN where it cannot be
    computed), so values are never carried over from an older date.
    """
    runnable: list[DerivedAttribute] = []
    for d in derived:
        bad = sorted({c for c in d.sources.values() if c in errors})
        if bad:
            errors[d.column_id] = f"source attribute(s) failed this run: {bad}"
        else:
            runnable.append(d)
    if not runnable:
        return

    start = time.monotonic()
    needed = list(dict.fromkeys(c for d in runnable for c in d.sources.values()))
    n_rows = max(d.lookback_rows for d in runnable)
    try:  # one history query for everything, sliced per derived field below
        hist = oracle.fetch_history(conn, [raw_by_id[c] for c in needed], run_date, n_rows, settings)
    except Exception as exc:
        log.error("History query failed: %s", _describe(exc))
        for d in runnable:
            errors[d.column_id] = f"history query failed: {_describe(exc)}"
        return
    today_ids = sorted(hist.loc[hist["as_of_date"].dt.date == run_date, "stock_id"].unique())
    base = hist[hist["stock_id"].isin(today_ids)]
    log.info("HISTORY %d rows | %d stocks with data on %s | up to %d rows each | %.2fs",
             len(hist), len(today_ids), run_date, n_rows, time.monotonic() - start)

    for d in runnable:
        t0 = time.monotonic()
        try:
            if not today_ids:
                raise ValueError(f"no source rows in Oracle for {run_date}")
            h = base[["stock_id", "as_of_date"]].copy()
            for role, col in d.sources.items():
                h[role] = base[col]
            h = h.groupby("stock_id", sort=False).tail(d.lookback_rows)
            out = _validate_output(d.derive(h, run_date, **d.params), allow_empty=True)
            values = pd.to_numeric(out.set_index("stock_id")["value"].reindex(today_ids), errors="coerce")
            frames[d.column_id] = pd.DataFrame({"stock_id": today_ids, "value": values.to_numpy()})
            log.info("DERIVED %s | %d stocks, %d with values | %.2fs", d.column_id, len(values),
                     int(values.notna().sum()), time.monotonic() - t0)
        except Exception as exc:
            log.error("%s: derivation failed: %s", d.column_id, _describe(exc), exc_info=True)
            errors[d.column_id] = f"derivation failed: {_describe(exc)}"


def run(run_date: date, project_root: Path, force_download: bool = False,
        only: list[str] | None = None, skip_upload: bool = False, skip_derived: bool = False) -> int:
    """Run the whole pipeline for ``run_date``. Returns the process exit code."""
    try:
        settings = load_settings(project_root / "config" / "settings.yaml", project_root)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return EXIT_CONFIG

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(settings.log_dir / f"run_{run_date:%Y-%m-%d}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    try:
        return _run(run_date, project_root, settings, force_download, only, skip_upload, skip_derived)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def _run(run_date: date, root: Path, settings: Settings, force: bool, only: list[str] | None,
         skip_upload: bool, skip_derived: bool) -> int:
    started = time.monotonic()
    log.info("Run started for %s", run_date)

    # 1-3. Validate everything that doesn't need the network, then group.
    try:
        raw = load_attributes(root / "config" / "attributes.yaml", settings)
        derived = load_derived(root / "config" / "derived.yaml", settings, raw)
        everything: list[Column] = [*raw, *derived]
        selected = _select(everything, only)
        if skip_derived:
            selected = [c for c in selected if not isinstance(c, DerivedAttribute)]
        sel_raw = [c for c in selected if isinstance(c, Attribute)]
        plan = Plan(
            all_columns=everything,
            raw_by_id={a.column_id: a for a in raw},
            raw=sel_raw,
            derived=[c for c in selected if isinstance(c, DerivedAttribute)],
            groups=fetch.group_by_path(sel_raw, settings.offline_root, run_date),
        )
        check_env(settings, need_firebase=not skip_upload)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return EXIT_CONFIG

    try:
        conn = oracle.connect(settings)
    except Exception as exc:
        log.error("Oracle connection failed: %s", _describe(exc))
        return EXIT_FATAL
    try:
        return _execute(conn, run_date, settings, plan, force, skip_upload, started)
    finally:
        conn.close()


def _execute(conn, run_date: date, settings: Settings, plan: Plan, force: bool, skip_upload: bool,
             started: float) -> int:
    # Schema check happens before any download.
    try:
        oracle.check_columns(conn, plan.all_columns, settings)
    except ConfigError as exc:
        log.error("Schema validation failed: %s", exc)
        return EXIT_CONFIG
    except Exception as exc:
        log.error("Oracle schema check failed: %s", _describe(exc))
        return EXIT_FATAL

    # 4. Process groups in parallel; cache-hit groups first (stable sort keeps config order).
    ordered = sorted(plan.groups.items(), key=lambda kv: force or not fetch.is_cached(kv[0]))
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = [pool.submit(_process_group, p, a, run_date, settings, force) for p, a in ordered]
        for fut in futures:
            res = fut.result()
            frames.update(res.frames)
            errors.update(res.errors)

    # 5. Raw values first (one MERGE per table), then derived fields computed from what is now in Oracle.
    _write(conn, plan.raw, frames, errors, run_date, settings)
    if plan.derived:
        _run_derived(conn, plan.derived, plan.raw_by_id, frames, errors, run_date, settings)
        _write(conn, plan.derived, frames, errors, run_date, settings)

    # 6. Publish.
    fatal = False
    if errors and not settings.upload_on_partial_failure:
        log.warning("Skipping CSV build/upload: %d attribute(s) failed (upload_on_partial_failure=false)", len(errors))
    else:
        try:
            csv_path = publish.build_csv(conn, plan.all_columns, run_date, settings)
            log.info("CSV written: %s", csv_path)
            if skip_upload:
                log.info("--skip-upload set; not uploading")
            else:
                log.info("Uploaded %s", publish.upload_csv(csv_path, run_date, settings))
        except Exception as exc:
            log.error("Publishing failed: %s", _describe(exc), exc_info=True)
            fatal = True

    # 7. Summary.
    total = len(plan.raw) + len(plan.derived)
    log.info("SUMMARY date=%s attributes=%d ok=%d failed=%d elapsed=%.1fs", run_date, total,
             total - len(errors), len(errors), time.monotonic() - started)
    for column_id, msg in errors.items():
        log.error("FAILED %s: %s", column_id, msg)
    return EXIT_FATAL if fatal else (EXIT_PARTIAL if errors else EXIT_OK)
