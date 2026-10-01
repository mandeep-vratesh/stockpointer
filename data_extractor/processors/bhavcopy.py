"""Example processors: several attributes read the SAME bhavcopy file (grouped -> downloaded once).

Raw extraction only. Adjust the column-name map to match your real source.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

# logical field -> accepted header names (legacy / new bhavcopy layouts)
_COLUMNS = {
    "symbol": ("SYMBOL",),
    "series": ("SERIES",),
    "open": ("OPEN_PRICE",),
    "high": ("HIGH_PRICE",),
    "low": ("LOW_PRICE",),
    "close": ("CLOSE_PRICE",),
    "volume": ("TTL_TRD_QNTY",),
    "deliv": ("DELIV_QTY",),
}


def _load(file_path: str) -> pd.DataFrame:
    """Read the bhavcopy, keep equity series, and normalise column names."""
    df = pd.read_csv(file_path, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for logical, candidates in _COLUMNS.items():
        found = next((c for c in candidates if c in df.columns), None)
        if found is None:
            raise ValueError(f"none of {candidates} found in {file_path}")
        rename[found] = logical
    df = df.rename(columns=rename)[list(_COLUMNS)]
    df["symbol"] = df["symbol"].astype(str).str.strip()
    return df[df["series"].astype(str).str.strip() == "EQ"]


def _extract(file_path: str, field: str) -> pd.DataFrame:
    df = _load(file_path)
    out = pd.DataFrame({"stock_id": df["symbol"], "value": pd.to_numeric(df[field], errors="coerce")})
    return out.drop_duplicates("stock_id", keep="first").reset_index(drop=True)


def extract_close(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw closing price per stock."""
    return _extract(file_path, "close")


def extract_volume(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw traded quantity per stock."""
    return _extract(file_path, "volume")


def extract_open(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw opening price per stock."""
    return _extract(file_path, "open")


def extract_high(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw day high per stock."""
    return _extract(file_path, "high")


def extract_low(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw day low per stock."""
    return _extract(file_path, "low")


def extract_delivery(file_path: str, run_date: date) -> pd.DataFrame:
    """Raw delivered quantity per stock (blank where the exchange reports '-')."""
    return _extract(file_path, "deliv")
