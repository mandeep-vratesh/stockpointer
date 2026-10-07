#!/usr/bin/env python3
"""
Generate src/config/symbolGroups.config.json from NSE index constituent CSVs.

Run manually after an index rebalancing:

    python scripts/generate_symbol_groups.py
    python scripts/generate_symbol_groups.py --output path/to/symbolGroups.config.json
    python scripts/generate_symbol_groups.py --allow-partial   # keep going if some downloads fail

Edit INDEX_SOURCES below: { segment label: { index label: constituent CSV url } }.
Each CSV must have a "Symbol" column (the standard NSE / niftyindices format:
Company Name, Industry, Symbol, Series, ISIN Code). Standard library only.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- EDIT ME
# NOTE: these URLs follow the niftyindices.com constituent-list pattern but were not
# verified here. Open each one in a browser once; fix or remove any that 404.
BASE = "https://niftyindices.com/IndexConstituent"
INDEX_SOURCES = {
    "Broad Market": {
        "Nifty 50": f"{BASE}/ind_nifty50list.csv",
        "Nifty Next 50": f"{BASE}/ind_niftynext50list.csv",
        "Nifty 100": f"{BASE}/ind_nifty100list.csv",
        "Nifty 200": f"{BASE}/ind_nifty200list.csv",
        "Nifty 500": f"{BASE}/ind_nifty500list.csv",
        "Nifty Midcap 50": f"{BASE}/ind_niftymidcap50list.csv",
        "Nifty Midcap 100": f"{BASE}/ind_niftymidcap100list.csv",
        "Nifty Midcap 150": f"{BASE}/ind_niftymidcap150list.csv",
        "Nifty Smallcap 50": f"{BASE}/ind_niftysmallcap50list.csv",
        "Nifty Smallcap 100": f"{BASE}/ind_niftysmallcap100list.csv",
        "Nifty Smallcap 250": f"{BASE}/ind_niftysmallcap250list.csv",
        "Nifty LargeMidcap 250": f"{BASE}/ind_niftylargemidcap250list.csv",
        "Nifty MidSmallcap 400": f"{BASE}/ind_niftymidsmallcap400list.csv",
    },
    "Sectoral": {
        "Nifty Bank": f"{BASE}/ind_niftybanklist.csv",
        "Nifty IT": f"{BASE}/ind_niftyitlist.csv",
        "Nifty Pharma": f"{BASE}/ind_niftypharmalist.csv",
        "Nifty FMCG": f"{BASE}/ind_niftyfmcglist.csv",
        "Nifty Auto": f"{BASE}/ind_niftyautolist.csv",
        "Nifty Metal": f"{BASE}/ind_niftymetallist.csv",
        "Nifty Energy": f"{BASE}/ind_niftyenergylist.csv",
        "Nifty Realty": f"{BASE}/ind_niftyrealtylist.csv",
        "Nifty Financial Services": f"{BASE}/ind_niftyfinancelist.csv",
    },
    "Thematic": {
        "Nifty India Consumption": f"{BASE}/ind_niftyconsumptionlist.csv",
        "Nifty Infrastructure": f"{BASE}/ind_niftyinfralist.csv",
    },
    "Strategy": {
        "Nifty100 Quality 30": f"{BASE}/ind_nifty100Quality30list.csv",
    },
}
DEFAULT_INDEX = "Nifty 50"  # selected on first login; falls back to "All stocks" if not listed
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "config" / "symbolGroups.config.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,*/*",
}


def slug(label: str) -> str:
    """Firebase-safe id (no . $ # [ ] /), e.g. 'Nifty Next 50' -> 'NIFTY_NEXT_50'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()


def fetch(url: str, retries: int = 3) -> str:
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(attempt)
    raise RuntimeError(f"download failed: {last}")


def parse_symbols(text: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
    if "symbol" not in cols:
        raise RuntimeError(f"no 'Symbol' column (found: {list(cols)})")
    seen, out = set(), []
    for row in reader:
        sym = (row.get(cols["symbol"]) or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    if not out:
        raise RuntimeError("CSV contained no symbols")
    return sorted(out)


def load_previous(path: Path) -> dict[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {i["id"]: i["symbols"] for s in data.get("segments", []) for i in s.get("indices", [])}
    except (OSError, ValueError, KeyError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--allow-partial", action="store_true",
                    help="write the file even if some downloads fail (previous symbols are reused when available)")
    args = ap.parse_args()

    previous = load_previous(args.output)
    segments, errors, used_ids, default_id = [], [], set(), None

    for seg_label, indices in INDEX_SOURCES.items():
        seg = {"id": slug(seg_label), "label": seg_label, "indices": []}
        for label, url in indices.items():
            gid = slug(label)
            if gid in used_ids or gid == "ALL":
                raise SystemExit(f"Duplicate/reserved group id '{gid}' from '{label}'. Rename the index label.")
            used_ids.add(gid)
            try:
                symbols = parse_symbols(fetch(url))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{seg_label} / {label}: {e}  ({url})")
                print(f"  FAIL  {label}: {e}")
                if args.allow_partial and gid in previous:
                    symbols = previous[gid]
                    print(f"        reusing {len(symbols)} previous symbols")
                else:
                    continue
            else:
                old = set(previous.get(gid, []))
                diff = f"  (+{len(set(symbols) - old)} / -{len(old - set(symbols))})" if old else "  (new)"
                print(f"  ok    {label}: {len(symbols)} stocks{diff}")
            seg["indices"].append({"id": gid, "label": label, "symbols": symbols})
            if label == DEFAULT_INDEX:
                default_id = gid
        if seg["indices"]:
            segments.append(seg)

    if errors and not args.allow_partial:
        print(f"\n{len(errors)} download(s) failed; config NOT written (use --allow-partial to override):")
        print("\n".join(f"  - {e}" for e in errors))
        return 1

    out = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "defaultGroup": default_id, "segments": segments}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    total = sum(len(i["symbols"]) for s in segments for i in s["indices"])
    print(f"\nWrote {args.output} ({sum(len(s['indices']) for s in segments)} indices, {total} memberships).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
