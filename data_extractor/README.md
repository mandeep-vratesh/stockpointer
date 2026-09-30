# Stock Pointer

Config-driven pipeline: for a run date, get each attribute's source document (offline copy first,
download otherwise), extract **raw** per-stock values, MERGE them into Oracle, then build one CSV
from Oracle and upload it to Firebase Storage. No scoring, ranking or totals happen here.

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
```

To persist a variable across sessions use `setx NAME "value"` (then open a new terminal), or set it in
*System Properties > Environment Variables*. In `cmd.exe` use `set NAME=value`.

**Linux / macOS**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ORACLE_USER=... ORACLE_PASSWORD=... ORACLE_DSN=host:1521/service
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json   # not needed with --skip-upload
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
- The CSV always contains every configured attribute (even with `--only`), read from Oracle.

## Running

```bash
python main.py                                # today   (Windows: py main.py, or python main.py in the venv)
python main.py --date 2026-09-25              # backdated (uses offline copy, else downloads)
python main.py --force-download               # ignore offline copies
python main.py --only close_price volume      # subset of attributes ("a,b" also works; quote it in PowerShell)
python main.py --skip-upload                  # still writes Oracle + local CSV
```

Exit codes: `0` success, `1` partial failure, `2` config/CLI/schema error, `3` fatal (DB/Firebase).
Logs go to stdout and `logs/run_{date}.log`. Output: `data/reports/stock_data_{date}.csv` and
`gs://<bucket>/reports/{date}/stock_data_{date}.csv` (private, overwritten on re-run).

Backfills are safe: Oracle rows and the Firebase path are keyed by the run date, and re-running a date
is idempotent. If the source no longer serves an old date and no offline copy exists, that group fails
normally (exit 1). To backfill from files you already have, drop them at the rendered `offline_path`.

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

`downloaders/nse.py` + `processors/bhavcopy.py` are the worked example: two attributes
(`close_price`, `volume`) share one bhavcopy file, so it is downloaded once and read twice.
Adjust the header map in `processors/bhavcopy.py` to your real file layout.
