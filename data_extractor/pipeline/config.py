"""Load and validate configs, resolve callables, render date templates."""
from __future__ import annotations

import importlib
import os
import re
import string
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any, Callable

import yaml

IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
REQUIRED_ATTR_KEYS = (
    "column_id", "download_fn", "download_url", "offline_path",
    "post_process_fn", "oracle_table", "oracle_column",
)
_SAMPLE_DATE = date(2000, 1, 1)
_WIN_BAD_CHARS = frozenset('<>:"|?*')  # not allowed in Windows file names


class ConfigError(Exception):
    """Invalid configuration, CLI usage or environment (exit code 2)."""


@dataclass(frozen=True)
class OracleSettings:
    user_env: str
    password_env: str
    dsn_env: str
    stock_id_column: str = "STOCK_ID"
    date_column: str = "AS_OF_DATE"


@dataclass(frozen=True)
class FirebaseSettings:
    credentials_env: str
    bucket: str
    report_prefix: str = "reports"


@dataclass(frozen=True)
class DownloadSettings:
    timeout_seconds: int = 60
    max_retries: int = 3  # retries after the first attempt


@dataclass(frozen=True)
class Settings:
    offline_root: Path
    report_dir: Path
    oracle: OracleSettings
    firebase: FirebaseSettings
    download: DownloadSettings
    max_workers: int = 4
    upload_on_partial_failure: bool = False
    log_dir: Path = Path("logs")


@dataclass(frozen=True)
class Attribute:
    column_id: str
    download_fn: str
    download_url: str
    offline_path: str
    post_process_fn: str
    oracle_table: str    # normalised to upper case (unquoted Oracle identifiers)
    oracle_column: str   # normalised to upper case
    download: Callable[..., None] = field(compare=False, repr=False)
    process: Callable[..., Any] = field(compare=False, repr=False)


# --------------------------------------------------------------------------- helpers
def _read_yaml(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8-sig") as fh:  # tolerate a BOM (Notepad / PowerShell)
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc


def _abs(base: Path, value: str | os.PathLike) -> Path:
    return (base / value).resolve()


def resolve_callable(dotted: str) -> Callable[..., Any]:
    """Import ``package.module.func`` and return the callable."""
    module_name, _, attr = dotted.rpartition(".")
    if not module_name:
        raise ConfigError(f"{dotted!r} is not a dotted path")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # import errors of any kind
        raise ConfigError(f"Cannot import {module_name!r} (from {dotted!r}): {exc}") from exc
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise ConfigError(f"{dotted!r} does not exist or is not callable")
    return fn


def render_template(template: str, run_date: date) -> str:
    """Render ``{date}`` / ``{date:%Y%m%d}`` templates; other placeholders are rejected."""
    try:
        for _, name, _, _ in string.Formatter().parse(template):
            if name is not None and name != "date":
                raise ConfigError(
                    f"Unsupported placeholder {{{name}}} in {template!r}; only {{date}} is allowed"
                )
        return template.format(date=run_date)
    except (ValueError, KeyError, IndexError, AttributeError) as exc:
        raise ConfigError(f"Bad template {template!r}: {exc}") from exc


def resolve_offline_path(offline_root: Path, template: str, run_date: date) -> Path:
    """Render an offline_path template to an absolute path guaranteed to live under offline_root."""
    root = os.path.normpath(offline_root)
    rendered = render_template(template, run_date)
    if os.name == "nt" and _WIN_BAD_CHARS & set(rendered):
        raise ConfigError(f"offline_path {template!r} renders to {rendered!r}, which has characters "
                          f"not allowed in Windows paths ({''.join(sorted(_WIN_BAD_CHARS))})")
    full = os.path.normpath(os.path.join(root, rendered))
    try:
        # normcase makes the comparison case-insensitive on Windows (no-op on POSIX)
        n_root, n_full = os.path.normcase(root), os.path.normcase(full)
        inside = os.path.commonpath([n_root, n_full]) == n_root and n_full != n_root
    except ValueError:  # e.g. different drives on Windows
        inside = False
    if not inside:
        raise ConfigError(f"offline_path {template!r} escapes offline_root")
    return Path(full)


# --------------------------------------------------------------------------- settings
def load_settings(path: Path, base_dir: Path) -> Settings:
    """Load settings.yaml; relative paths are resolved against ``base_dir`` (project root)."""
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    allowed = {f.name for f in fields(Settings)}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"Unknown settings keys: {sorted(unknown)}")
    try:
        settings = Settings(
            offline_root=_abs(base_dir, raw["offline_root"]),
            report_dir=_abs(base_dir, raw["report_dir"]),
            oracle=OracleSettings(**raw["oracle"]),
            firebase=FirebaseSettings(**raw["firebase"]),
            download=DownloadSettings(**(raw.get("download") or {})),
            max_workers=int(raw.get("max_workers", 4)),
            upload_on_partial_failure=bool(raw.get("upload_on_partial_failure", False)),
            log_dir=_abs(base_dir, raw.get("log_dir", "logs")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid settings in {path}: {exc!r}") from exc

    if settings.max_workers < 1:
        raise ConfigError("max_workers must be >= 1")
    if settings.download.timeout_seconds <= 0 or settings.download.max_retries < 0:
        raise ConfigError("download.timeout_seconds must be > 0 and download.max_retries >= 0")
    for col in (settings.oracle.stock_id_column, settings.oracle.date_column):
        if not IDENT_RE.match(col):
            raise ConfigError(f"Invalid Oracle identifier in settings: {col!r}")
    return settings


def check_env(settings: Settings, need_firebase: bool) -> None:
    """Fail fast if required secrets are missing from the environment."""
    names = [settings.oracle.user_env, settings.oracle.password_env, settings.oracle.dsn_env]
    if need_firebase:
        names.append(settings.firebase.credentials_env)
        names.append(settings.firebase.bucket)
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ConfigError(f"Missing environment variables: {', '.join(missing)}")


# --------------------------------------------------------------------------- attributes
def _build_attribute(entry: Any) -> Attribute:
    if not isinstance(entry, dict):
        raise ConfigError("must be a mapping")
    keys = set(entry)
    missing = [k for k in REQUIRED_ATTR_KEYS if k not in keys]
    unknown = sorted(keys - set(REQUIRED_ATTR_KEYS))
    if missing or unknown:
        raise ConfigError(f"missing keys {missing}, unknown keys {unknown}")
    for k in REQUIRED_ATTR_KEYS:
        if not isinstance(entry[k], str) or not entry[k].strip():
            raise ConfigError(f"{k} must be a non-empty string")
    for k in ("oracle_table", "oracle_column"):
        if not IDENT_RE.match(entry[k]):
            raise ConfigError(f"{k}={entry[k]!r} is not a valid identifier")

    # Validate templates now (rendering with a sample date) so errors surface before any download.
    render_template(entry["download_url"], _SAMPLE_DATE)
    resolve_offline_path(Path(os.path.abspath(os.sep)) / "root", entry["offline_path"], _SAMPLE_DATE)

    return Attribute(
        column_id=entry["column_id"],
        download_fn=entry["download_fn"],
        download_url=entry["download_url"],
        offline_path=entry["offline_path"],
        post_process_fn=entry["post_process_fn"],
        oracle_table=entry["oracle_table"].upper(),
        oracle_column=entry["oracle_column"].upper(),
        download=resolve_callable(entry["download_fn"]),
        process=resolve_callable(entry["post_process_fn"]),
    )


def load_attributes(path: Path, settings: Settings) -> list[Attribute]:
    """Load and fully validate attributes.yaml (all problems are reported together)."""
    raw = _read_yaml(path)
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{path} must contain a non-empty list of attributes")

    errors: list[str] = []
    attrs: list[Attribute] = []
    for i, entry in enumerate(raw, 1):
        label = f"entry #{i}" + (f" ({entry['column_id']})" if isinstance(entry, dict) and "column_id" in entry else "")
        try:
            attrs.append(_build_attribute(entry))
        except ConfigError as exc:
            errors.append(f"{label}: {exc}")

    seen_ids: set[str] = set()
    seen_cols: set[tuple[str, str]] = set()
    key_cols = {settings.oracle.stock_id_column.upper(), settings.oracle.date_column.upper()}
    for a in attrs:
        if a.column_id in seen_ids:
            errors.append(f"duplicate column_id {a.column_id!r}")
        seen_ids.add(a.column_id)
        pair = (a.oracle_table, a.oracle_column)
        if pair in seen_cols:
            errors.append(f"duplicate target {a.oracle_table}.{a.oracle_column}")
        seen_cols.add(pair)
        if a.column_id == "stock_id":
            errors.append("column_id 'stock_id' is reserved for the CSV key column")
        if a.oracle_column in key_cols:
            errors.append(f"{a.column_id}: oracle_column {a.oracle_column} is a key column")

    if errors:
        raise ConfigError("Invalid attributes config:\n  - " + "\n  - ".join(errors))
    return attrs
