"""Oracle access: connection, schema check, MERGE upsert, report query."""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date

import oracledb
import pandas as pd

from .config import Attribute, ConfigError, Settings

log = logging.getLogger(__name__)
BATCH_SIZE = 1000


def connect(settings: Settings) -> oracledb.Connection:
    """Open a connection using credentials from environment variables."""
    o = settings.oracle
    return oracledb.connect(
        user=os.environ[o.user_env], password=os.environ[o.password_env], dsn=os.environ[o.dsn_env]
    )


def check_columns(conn: oracledb.Connection, attributes: list[Attribute], settings: Settings) -> None:
    """Verify every target table/column (and key columns) exists in ALL_TAB_COLUMNS. Never alters schema."""
    key_cols = {settings.oracle.stock_id_column.upper(), settings.oracle.date_column.upper()}
    required: dict[str, set[str]] = defaultdict(lambda: set(key_cols))
    for a in attributes:
        required[a.oracle_table].add(a.oracle_column)
    tables = sorted(required)
    binds = {f"t{i}": t for i, t in enumerate(tables)}
    sql = ("SELECT table_name, column_name FROM all_tab_columns WHERE table_name IN ("
           + ", ".join(f":{k}" for k in binds) + ")")
    present: dict[str, set[str]] = defaultdict(set)
    with conn.cursor() as cur:
        for table, column in cur.execute(sql, binds):
            present[table].add(column)
    missing = [f"{t}.{c}" for t in tables for c in sorted(required[t]) if c not in present[t]]
    if missing:
        raise ConfigError("Not found in ALL_TAB_COLUMNS: " + ", ".join(missing))


def build_merge_sql(table: str, columns: list[str], settings: Settings) -> str:
    """Build the MERGE statement for one table (bind names are positional-safe: v0, v1, ...)."""
    o = settings.oracle
    n = len(columns)
    binds = ", ".join(f":v{i} AS v{i}" for i in range(n))
    sets = ", ".join(f"t.{c} = s.v{i}" for i, c in enumerate(columns))
    ins_cols = ", ".join([o.stock_id_column, o.date_column, *columns])
    ins_vals = ", ".join(["s.stock_id", "s.as_of_date", *(f"s.v{i}" for i in range(n))])
    return (
        f"MERGE INTO {table} t\n"
        f"USING (SELECT :stock_id AS stock_id, :as_of_date AS as_of_date, {binds} FROM dual) s\n"
        f"ON (t.{o.stock_id_column} = s.stock_id AND t.{o.date_column} = s.as_of_date)\n"
        f"WHEN MATCHED THEN UPDATE SET {sets}\n"
        f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})"
    )


def upsert_table(conn: oracledb.Connection, table: str, columns: list[tuple[str, pd.DataFrame]],
                 run_date: date, settings: Settings) -> int:
    """Outer-join the attribute frames into one wide frame and MERGE it in one transaction.

    ``columns`` is a list of ``(oracle_column, DataFrame[stock_id, value])``. Returns rows written.
    Commits on success; rolls back this table and re-raises on failure.
    """
    names = [c for c, _ in columns]
    # object dtype keeps ints as ints (no float coercion when the outer join introduces gaps)
    wide = pd.concat(
        [df.set_index("stock_id")["value"].astype(object).rename(col) for col, df in columns],
        axis=1, join="outer",
    ).sort_index()

    cols = [[None if pd.isna(v) else v for v in wide[c].tolist()] for c in names]  # NaN -> None
    rows = [
        {"stock_id": sid, "as_of_date": run_date, **{f"v{i}": cols[i][j] for i in range(len(names))}}
        for j, sid in enumerate(wide.index.tolist())
    ]
    sql = build_merge_sql(table, names, settings)
    with conn.cursor() as cur:
        try:
            for start in range(0, len(rows), BATCH_SIZE):
                cur.executemany(sql, rows[start:start + BATCH_SIZE])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return len(rows)


def build_report_sql(attributes: list[Attribute], settings: Settings) -> str:
    """SQL that full-outer-joins every target table on stock_id for one date (bind: run_date)."""
    o = settings.oracle
    tables = list(dict.fromkeys(a.oracle_table for a in attributes))
    alias = {t: f"t{i}" for i, t in enumerate(tables)}

    def coalesce(exprs: list[str]) -> str:
        return exprs[0] if len(exprs) == 1 else f"COALESCE({', '.join(exprs)})"

    subqueries = []
    for t in tables:
        sel = ", ".join(f"{a.oracle_column} AS c{i}" for i, a in enumerate(attributes) if a.oracle_table == t)
        subqueries.append(
            f"(SELECT {o.stock_id_column} AS stock_id, {sel} FROM {t} WHERE {o.date_column} = :run_date) {alias[t]}"
        )
    from_clause = subqueries[0]
    joined = [f"{alias[tables[0]]}.stock_id"]
    for t, sub in zip(tables[1:], subqueries[1:]):
        from_clause += f"\nFULL OUTER JOIN {sub} ON {coalesce(joined)} = {alias[t]}.stock_id"
        joined.append(f"{alias[t]}.stock_id")

    select = [f"{coalesce(joined)} AS stock_id"] + [f"{alias[a.oracle_table]}.c{i}" for i, a in enumerate(attributes)]
    return f"SELECT {', '.join(select)}\nFROM {from_clause}\nORDER BY 1"


def fetch_report(conn: oracledb.Connection, attributes: list[Attribute], run_date: date,
                 settings: Settings) -> pd.DataFrame:
    """Return ``stock_id`` + one column per attribute (named by column_id, config order)."""
    sql = build_report_sql(attributes, settings)
    with conn.cursor() as cur:
        cur.execute(sql, {"run_date": run_date})
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["stock_id", *(a.column_id for a in attributes)])
