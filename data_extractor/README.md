# Stock Pointer

Config-driven pipeline: for a run date, get each attribute's source document (offline copy first,
download otherwise), extract **raw** per-stock values, MERGE them into Oracle, then build one CSV
from Oracle and upload it to Firebase Storage. Technical indicators (RSI, moving averages, ...) and a
delivery ratio are then **derived** from the stored history (see *Derived fields*). No scoring, ranking
or totals happen here.

## Setup

**Windows 11 (PowerShell)**

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1       # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

# names of these variables are set in config/settings.yaml; these last for the current session
$env:ORACLE_USER = "..."
$env:ORACLE_PASSWORD = "..."
$env:ORACLE_DSN = "host:1521/service"
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\secrets\service-account.json"   # not needed with --skip-upload
$env:FIREBASE_BUCKET = "my-bucket.appspot.com"                                # not needed with --skip-upload
```

Instead of exporting variables you can put them in a `.env` file in the project root (loaded by
python-dotenv; keep it out of version control). `firebase.bucket` in `settings.yaml` holds the **name of
the environment variable** that contains the bucket (default `FIREBASE_BUCKET`), not the bucket itself.

To persist a variable across sessions use `setx NAME "value"` (then open a new terminal), or set it in
*System Properties > Environment Variables*. In `cmd.exe` use `set NAME=value`.

**Linux / macOS**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ORACLE_USER=... ORACLE_PASSWORD=... ORACLE_DSN=host:1521/service
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json FIREBASE_BUCKET=my-bucket.appspot.com
```

python-oracledb runs in "thin" mode by default, so **no Oracle Client install is needed** on Windows.

### Windows notes

- Use `/` or `\` in `settings.yaml` paths; single-quote Windows paths in YAML (`'C:\data\offline'`)
  so backslashes are not treated as escapes. Relative paths resolve against the project root.
- `offline_path` templates are checked case-insensitively on Windows and must not render characters
  Windows forbids in file names (`< > : " | ? *`). Use `%Y%m%d` or `%Y-%m-%d`, never a time with `:`.
- Very deep `offline_root` folders can hit the 260-character path limit; enable long paths
  (`LongPathsEnabled` in the registry / Group Policy) or keep `offline_root` short.
- If a file in `offline_root` is open in another program (e.g. Excel), replacing it can fail; the
  download is retried, but close the file if it keeps failing.
- Console output and log files are UTF-8. The CSV is UTF-8 without BOM with `\n` line endings on every
  OS; Excel opens it fine, but use *Data > From Text/CSV* if it mis-detects non-ASCII characters.
- Source files saved by Windows tools may be cp1252 rather than UTF-8; pass `encoding=` in your
  processor's `read_csv` if so.

Edit `config/settings.yaml` (bucket, key column names, paths) and `config/attributes.yaml`.
Relative paths in settings resolve against the project root.

## Assumptions (please confirm)

- Target tables **already exist** and are keyed by `(STOCK_ID, AS_OF_DATE)` (names are global settings).
  The schema is never altered; the run aborts (exit 2) before any download if a table/column is missing.
- `AS_OF_DATE` is a `DATE` holding midnight (the run date is bound as a date and compared with `=`).
- Table/column names are upper-cased on load (unquoted Oracle identifiers) and looked up in
  `ALL_TAB_COLUMNS` by name only (no owner filter). Make sure the name is unambiguous for your user.
- `post_process_fn` returns exactly the columns `stock_id`, `value`, with unique non-empty IDs and at
  least one row. Zero rows is treated as a processor failure rather than silent success.
- `download.max_retries` = retries after the first attempt (3 => up to 4 attempts), exponential backoff.
- In a MERGE, a stock present for one attribute of a table but absent for another gets **NULL** for the
  absent column (the outer join). Only columns produced in the run are touched, so `--only` never
  affects other columns.
- If any attribute fails, CSV build **and** upload are skipped unless `upload_on_partial_failure: true`.
- The CSV always contains every configured attribute, raw and derived (even with `--only`), read from Oracle.
- Derived fields read their history **from Oracle**, so the needed days must already be stored (see
  *Backfilling history*). Prices are as stored (unadjusted), so splits/bonus issues distort indicators
  around those dates. `lookback_rows` counts rows (trading days present), so holidays are not an issue.
- A derived value is **NULL (blank in the CSV)** whenever it cannot be computed: too little history, a NULL
  input (e.g. delivery shown as `-`), a zero denominator, or no row for the run date. It is never filled
  with 0 and never carried over from an earlier date.

## Running

```bash
python main.py                                # today   (Windows: py main.py, or python main.py in the venv)
python main.py --date 2026-09-25              # backdated (uses offline copy, else downloads)
python main.py --force-download               # ignore offline copies
python main.py --only close_price volume      # subset of attributes ("a,b" also works; quote it in PowerShell)
python main.py --skip-upload                  # still writes Oracle + local CSV
python main.py --skip-derived                 # raw attributes only
python main.py --only rsi_14 sma_50           # derived only (reads today's raw values already in Oracle)
```

`--only` with raw ids does not recompute derived fields; list the derived ids too (or run without `--only`).

Exit codes: `0` success, `1` partial failure, `2` config/CLI/schema error, `3` fatal (DB/Firebase).
Logs go to stdout and `logs/run_{date}.log`. Output: `data/reports/stock_data_{date}.csv` and
`gs://<bucket>/reports/{date}/stock_data_{date}.csv` (private, overwritten on re-run).

Backfills are safe: Oracle rows and the Firebase path are keyed by the run date, and re-running a date
is idempotent. If the source no longer serves an old date and no offline copy exists, that group fails
normally (exit 1). To backfill from files you already have, drop them at the rendered `offline_path`.

## Derived fields (technical indicators)

`config/derived.yaml` defines fields computed **after** the raw values are written, from Oracle history:

```yaml
- column_id: rsi_14
  derive_fn: derivers.indicators.rsi          # fn(history, run_date, **params) -> DataFrame[stock_id, value]
  sources: {close: close_price}               # role -> raw column_id from attributes.yaml
  params: {window: 14}
  lookback_rows: 100                          # trading-day rows of history handed to the function
  oracle_table: STOCK_DATA
  oracle_column: RSI_14
```

Flow: raw write commits -> one history query (`ROW_NUMBER` per stock, last N rows up to the run date) ->
each derived field gets its slice -> results are validated and written with one MERGE per table.
A derived field is computed for exactly the stocks that have a row on the run date. If one of its source
attributes failed in the same run, it is marked failed instead of using stale data.

| Group | `derive_fn` (in `derivers/indicators.py`) | Roles needed |
| --- | --- | --- |
| Trend | `sma`, `ema`, `close_vs_sma`, `sma_ratio`, `macd` (line/signal/hist), `adx` (adx/plus_di/minus_di) | close (+high, low for adx) |
| Momentum | `rsi`, `roc`, `stochastic` (k/d), `williams_r`, `cci`, `gap_pct` | close (+high, low / open) |
| Volatility | `atr` (optionally % of close), `bollinger` (upper/lower/pct_b/bandwidth), `hist_volatility` | close (+high, low) |
| Volume | `mfi`, `cmf`, `vwap` (optionally distance %), `volume_ratio` | high, low, close, volume |
| 52-week range | `rolling_high`, `rolling_low`, `pct_from_high`, `pct_from_low` (window 252) | high / low / close |
| Delivery | `delivery_ratio` = avg delivery of last 5 rows / avg of last 252 rows | delivery |

The shipped file defines 36 fields. `deliv_ratio_5d_52w` is the "week's delivery over 52-week delivery"
ratio, built on `DELIV_QTY`; for a percentage-based ratio add a raw `DELIV_PER` attribute and point the
`delivery` role at it. Dependencies of each function (params, defaults) are in its docstring.

Rules of thumb for `lookback_rows`: SMA/Bollinger/etc. = the window; RSI, ATR, ADX, EMA, MACD = 3-5x the
window (smoothing is seeded with an SMA, so more history makes the seed irrelevant); 52-week fields = 252
(the first value appears after 252 stored trading days).

**Adding an indicator:** write `def my_indicator(hist, run_date, window=14)` in `derivers/` (use `_apply`
in `indicators.py` as a template: it hands you NumPy arrays per role and returns NaN when data is missing),
then add an entry to `derived.yaml` and the Oracle column.

### Oracle columns

`sql/add_columns.sql` adds the new raw columns (`OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `DELIV_QTY`) and
all 36 derived columns to `STOCK_DATA` as `NUMBER`. The pipeline never alters the schema; a missing column
aborts the run with exit code 2 before any download.

### Backfilling history

Indicators need prior days in Oracle. Load them oldest to newest (ideally from stored bhavcopies in
`offline_root`), raw first, then compute derived fields as you go:

```bash
python main.py --date 2025-09-01 --skip-upload      # repeat for each trading day, oldest first
```

Each run computes that day's indicators from the days already stored, so in date order the indicators
are correct for every day. 252 stored days are needed before the 52-week fields appear (blank before that).
To fill derived fields for days whose raw values are already stored, use `--only <derived ids>` per date.

## Attribute config

| Key | Meaning |
| --- | --- |
| `column_id` | Unique ID; also the CSV column name (`stock_id` is reserved) |
| `download_fn` | Dotted path to `fn(url, dest_path, run_date, settings) -> None` |
| `download_url` | URL template; only `{date}` / `{date:%Y%m%d}` placeholders allowed |
| `offline_path` | Path template under `offline_root` (`..` escapes rejected) |
| `post_process_fn` | Dotted path to `fn(file_path, run_date) -> DataFrame[stock_id, value]` |
| `oracle_table` / `oracle_column` | Target; must be unique as a pair |

Attributes whose rendered `offline_path` is identical form a **group**: the file is fetched once and
each processor reads it from disk. If configs in a group disagree on `download_fn`/`download_url`, the
first wins and a warning is logged. Cache-hit groups run first. Attributes sharing a table are written
in one MERGE.

## Adding an attribute

1. **Downloader** (skip if `downloaders.generic.http_download` is enough): add a function to
   `downloaders/` that writes the document to `dest_path` and raises on failure. Don't rename or
   check the file yourself; the fetcher passes `<final>.part` and renames it only if non-empty.
2. **Processor**: add a function to `processors/` returning a DataFrame with `stock_id` and `value`
   (raw, lightly cleaned/typed values only).
3. **Config**: append an entry to `config/attributes.yaml`. If it reads a file another attribute
   already fetches, reuse the same `offline_path`, `download_fn` and `download_url`.
4. Make sure the Oracle column exists, then run `python main.py --only your_column_id --skip-upload`.

`downloaders/nse.py` + `processors/bhavcopy.py` are the worked example: six attributes (close, volume,
open, high, low, delivery quantity) share one bhavcopy file, so it is downloaded once and read six times.
Adjust the header map in `processors/bhavcopy.py` to your real file layout.
