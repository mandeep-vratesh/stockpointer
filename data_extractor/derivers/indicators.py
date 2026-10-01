"""Technical indicators computed from stored bhavcopy history (OHLCV + delivery).

Every public function is a ``derive_fn`` for ``config/derived.yaml``::

    fn(history: DataFrame, run_date: date, **params) -> DataFrame[stock_id, value]

``history`` is long-format with columns ``stock_id``, ``as_of_date`` and one column per *role* named in
the config's ``sources`` (``close``, ``high``, ``low``, ``open``, ``volume``, ``delivery``), sorted by
date and already limited to ``lookback_rows`` rows per stock.

Missing data policy: a value is NaN (stored as NULL, written to the CSV as blank) whenever it cannot be
computed -- too little history, a NaN input, a zero denominator, or no row for ``run_date``. Nothing is
ever filled with 0.

Wilder/EMA smoothing is seeded with a simple average, so set ``lookback_rows`` to roughly 3-5x the window
for RSI, ATR, ADX, EMA and MACD (the effect of the seed fades with history).
"""
from __future__ import annotations

from datetime import date
from typing import Callable

import numpy as np
import pandas as pd


class _Insufficient(Exception):
    """Raised inside an indicator when there is not enough data; the stock's value becomes NaN."""


# --------------------------------------------------------------------------- helpers
def _apply(hist: pd.DataFrame, run_date: date, roles: tuple[str, ...],
           fn: Callable[[dict[str, np.ndarray]], float]) -> pd.DataFrame:
    """Run ``fn`` on each stock's arrays (one per role); NaN if data is missing or not current."""
    missing = [r for r in roles if r not in hist.columns]
    if missing:
        raise ValueError(f"history has no source role(s) {missing}; add them under 'sources' in derived.yaml")
    rows = []
    for sid, g in hist.groupby("stock_id", sort=False):
        g = g.dropna(subset=list(roles))
        value = np.nan
        if len(g) and g["as_of_date"].iloc[-1].date() == run_date:  # latest usable row must be run_date
            try:
                with np.errstate(all="ignore"):
                    value = float(fn({r: g[r].to_numpy(dtype=float) for r in roles}))
            except _Insufficient:
                pass
        rows.append((sid, value if np.isfinite(value) else np.nan))
    return pd.DataFrame(rows, columns=["stock_id", "value"])


def _tail(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) < n:
        raise _Insufficient
    return x[-n:]


def _last(x: np.ndarray) -> float:
    if len(x) == 0 or np.isnan(x[-1]):
        raise _Insufficient
    return float(x[-1])


def _smoothed(values: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Exponential smoothing seeded with the SMA of the first n values (NaN before index n-1)."""
    out = np.full(len(values), np.nan)
    if len(values) < n:
        return out
    seed = values[n - 1:].astype(float).copy()
    seed[0] = values[:n].mean()
    out[n - 1:] = pd.Series(seed).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return out


def _ema(values: np.ndarray, n: int) -> np.ndarray:
    return _smoothed(values, n, 2.0 / (n + 1))


def _wilder(values: np.ndarray, n: int) -> np.ndarray:
    return _smoothed(values, n, 1.0 / n)


def _true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """True range for rows 1..end (needs the previous close)."""
    return np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])


def _typical(a: dict[str, np.ndarray]) -> np.ndarray:
    return (a["high"] + a["low"] + a["close"]) / 3.0


def _check(**windows: int) -> None:
    for name, v in windows.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"{name} must be an integer >= 1, got {v!r}")


def _choice(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"output must be one of {allowed}, got {value!r}")
    return value


# --------------------------------------------------------------------------- trend
def sma(hist, run_date, window: int = 20):
    """Simple moving average of close."""
    _check(window=window)
    return _apply(hist, run_date, ("close",), lambda a: _tail(a["close"], window).mean())


def ema(hist, run_date, window: int = 20):
    """Exponential moving average of close."""
    _check(window=window)
    return _apply(hist, run_date, ("close",), lambda a: _last(_ema(a["close"], window)))


def close_vs_sma(hist, run_date, window: int = 50):
    """Distance of close from its SMA, in percent."""
    _check(window=window)
    return _apply(hist, run_date, ("close",), lambda a: (a["close"][-1] / _tail(a["close"], window).mean() - 1) * 100)


def sma_ratio(hist, run_date, fast: int = 50, slow: int = 200):
    """SMA(fast) / SMA(slow); above 1 means the short trend is above the long trend."""
    _check(fast=fast, slow=slow)
    return _apply(hist, run_date, ("close",),
                  lambda a: _tail(a["close"], fast).mean() / _tail(a["close"], slow).mean())


def macd(hist, run_date, fast: int = 12, slow: int = 26, signal: int = 9, output: str = "hist", pct: bool = False):
    """MACD. output: line | signal | hist. pct=True divides by close (x100) so stocks are comparable."""
    _check(fast=fast, slow=slow, signal=signal)
    _choice(output, ("line", "signal", "hist"))
    if fast >= slow:
        raise ValueError("fast must be smaller than slow")

    def f(a):
        c = a["close"]
        line = _ema(c, fast) - _ema(c, slow)
        if output == "line":
            v = _last(line)
        else:
            sig = _last(_ema(line[slow - 1:], signal))
            v = sig if output == "signal" else _last(line) - sig
        return v / c[-1] * 100 if pct else v
    return _apply(hist, run_date, ("close",), f)


def adx(hist, run_date, window: int = 14, output: str = "adx"):
    """Wilder's ADX. output: adx | plus_di | minus_di."""
    _check(window=window)
    _choice(output, ("adx", "plus_di", "minus_di"))

    def f(a):
        h, l, c = a["high"], a["low"], a["close"]
        if len(c) < 2 * window:
            raise _Insufficient
        up, down = h[1:] - h[:-1], l[:-1] - l[1:]
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        atr = _wilder(_true_range(h, l, c), window)
        pdi = 100 * _wilder(plus_dm, window) / atr
        mdi = 100 * _wilder(minus_dm, window) / atr
        if output == "plus_di":
            return _last(pdi)
        if output == "minus_di":
            return _last(mdi)
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
        return _last(_wilder(dx[window - 1:], window))
    return _apply(hist, run_date, ("high", "low", "close"), f)


# --------------------------------------------------------------------------- momentum
def rsi(hist, run_date, window: int = 14):
    """Wilder's RSI of close (0-100). Blank if the price was flat over the whole window."""
    _check(window=window)

    def f(a):
        d = np.diff(a["close"])
        gain = _last(_wilder(np.clip(d, 0, None), window))
        loss = _last(_wilder(np.clip(-d, 0, None), window))
        if loss == 0:
            return 100.0 if gain > 0 else np.nan
        return 100 - 100 / (1 + gain / loss)
    return _apply(hist, run_date, ("close",), f)


def roc(hist, run_date, window: int = 12):
    """Rate of change of close over ``window`` rows, in percent."""
    _check(window=window)

    def f(a):
        c = a["close"]
        if len(c) < window + 1:
            raise _Insufficient
        return (c[-1] / c[-1 - window] - 1) * 100
    return _apply(hist, run_date, ("close",), f)


def stochastic(hist, run_date, window: int = 14, smooth: int = 3, output: str = "k"):
    """Stochastic oscillator. output: k (fast %K) | d (SMA of %K over ``smooth``)."""
    _check(window=window, smooth=smooth)
    _choice(output, ("k", "d"))

    def f(a):
        hh = pd.Series(a["high"]).rolling(window).max().to_numpy()
        ll = pd.Series(a["low"]).rolling(window).min().to_numpy()
        k = 100 * (a["close"] - ll) / (hh - ll)
        return _last(k) if output == "k" else _last(pd.Series(k).rolling(smooth).mean().to_numpy())
    return _apply(hist, run_date, ("high", "low", "close"), f)


def williams_r(hist, run_date, window: int = 14):
    """Williams %R (-100..0)."""
    _check(window=window)

    def f(a):
        hh, ll = _tail(a["high"], window).max(), _tail(a["low"], window).min()
        return -100 * (hh - a["close"][-1]) / (hh - ll)
    return _apply(hist, run_date, ("high", "low", "close"), f)


def cci(hist, run_date, window: int = 20):
    """Commodity Channel Index."""
    _check(window=window)

    def f(a):
        tp = _typical(a)
        w = _tail(tp, window)
        return (tp[-1] - w.mean()) / (0.015 * np.abs(w - w.mean()).mean())
    return _apply(hist, run_date, ("high", "low", "close"), f)


def gap_pct(hist, run_date):
    """Opening gap versus the previous close, in percent."""
    def f(a):
        if len(a["close"]) < 2:
            raise _Insufficient
        return (a["open"][-1] / a["close"][-2] - 1) * 100
    return _apply(hist, run_date, ("open", "close"), f)


# --------------------------------------------------------------------------- volatility
def atr(hist, run_date, window: int = 14, pct: bool = False):
    """Wilder's Average True Range. pct=True gives ATR as a percent of close."""
    _check(window=window)

    def f(a):
        v = _last(_wilder(_true_range(a["high"], a["low"], a["close"]), window))
        return v / a["close"][-1] * 100 if pct else v
    return _apply(hist, run_date, ("high", "low", "close"), f)


def bollinger(hist, run_date, window: int = 20, num_std: float = 2.0, output: str = "pct_b"):
    """Bollinger Bands. output: upper | lower | pct_b | bandwidth (percent of the middle band)."""
    _check(window=window)
    _choice(output, ("upper", "lower", "pct_b", "bandwidth"))

    def f(a):
        w = _tail(a["close"], window)
        mid, sd = w.mean(), w.std()  # population std, the usual convention
        up, lo = mid + num_std * sd, mid - num_std * sd
        return {"upper": up, "lower": lo, "pct_b": (a["close"][-1] - lo) / (up - lo),
                "bandwidth": (up - lo) / mid * 100}[output]
    return _apply(hist, run_date, ("close",), f)


def hist_volatility(hist, run_date, window: int = 20, trading_days: int = 252):
    """Annualised historical volatility (percent) from daily log returns."""
    _check(window=window, trading_days=trading_days)

    def f(a):
        r = _tail(np.diff(np.log(a["close"])), window)
        return r.std(ddof=1) * np.sqrt(trading_days) * 100
    return _apply(hist, run_date, ("close",), f)


# --------------------------------------------------------------------------- volume
def mfi(hist, run_date, window: int = 14):
    """Money Flow Index (0-100)."""
    _check(window=window)

    def f(a):
        tp = _typical(a)
        if len(tp) < window + 1:
            raise _Insufficient
        flow = (tp * a["volume"])[1:][-window:]
        delta = np.diff(tp)[-window:]
        pos, neg = flow[delta > 0].sum(), flow[delta < 0].sum()
        if neg == 0:
            return 100.0 if pos > 0 else np.nan
        return 100 - 100 / (1 + pos / neg)
    return _apply(hist, run_date, ("high", "low", "close", "volume"), f)


def cmf(hist, run_date, window: int = 20):
    """Chaikin Money Flow (-1..1)."""
    _check(window=window)

    def f(a):
        h, l, c, v = (_tail(a[k], window) for k in ("high", "low", "close", "volume"))
        rng = h - l
        mfm = np.where(rng > 0, ((c - l) - (h - c)) / np.where(rng > 0, rng, 1.0), 0.0)
        return (mfm * v).sum() / v.sum()
    return _apply(hist, run_date, ("high", "low", "close", "volume"), f)


def vwap(hist, run_date, window: int = 20, pct: bool = False):
    """Rolling VWAP from typical price. pct=True gives close's distance from it, in percent."""
    _check(window=window)

    def f(a):
        tp, v = _tail(_typical(a), window), _tail(a["volume"], window)
        w = (tp * v).sum() / v.sum()
        return (a["close"][-1] / w - 1) * 100 if pct else w
    return _apply(hist, run_date, ("high", "low", "close", "volume"), f)


def volume_ratio(hist, run_date, window: int = 20):
    """Today's volume divided by the average of the previous ``window`` days."""
    _check(window=window)
    return _apply(hist, run_date, ("volume",), lambda a: a["volume"][-1] / _tail(a["volume"][:-1], window).mean())


# --------------------------------------------------------------------------- range / 52-week
def rolling_high(hist, run_date, window: int = 252):
    """Highest high over ``window`` rows (252 ~ 52 weeks)."""
    _check(window=window)
    return _apply(hist, run_date, ("high",), lambda a: _tail(a["high"], window).max())


def rolling_low(hist, run_date, window: int = 252):
    """Lowest low over ``window`` rows."""
    _check(window=window)
    return _apply(hist, run_date, ("low",), lambda a: _tail(a["low"], window).min())


def pct_from_high(hist, run_date, window: int = 252):
    """Close versus the highest high over ``window`` rows, in percent (<= 0)."""
    _check(window=window)
    return _apply(hist, run_date, ("high", "close"),
                  lambda a: (a["close"][-1] / _tail(a["high"], window).max() - 1) * 100)


def pct_from_low(hist, run_date, window: int = 252):
    """Close versus the lowest low over ``window`` rows, in percent (>= 0)."""
    _check(window=window)
    return _apply(hist, run_date, ("low", "close"),
                  lambda a: (a["close"][-1] / _tail(a["low"], window).min() - 1) * 100)


# --------------------------------------------------------------------------- delivery
def delivery_ratio(hist, run_date, short: int = 5, long: int = 252, min_periods: int | None = None):
    """Average delivery over the last ``short`` rows / average over the last ``long`` rows.

    Defaults give "this week's delivery vs the 52-week average" (5 / 252 trading days). Needs at least
    ``min_periods`` rows (default: ``long``) and a non-zero long average, otherwise the value is blank.
    Source role: ``delivery`` (e.g. DELIV_QTY; point it at a delivery-% column for a percentage ratio).
    """
    _check(short=short, long=long)
    need = long if min_periods is None else min_periods
    _check(min_periods=need)

    def f(a):
        d = a["delivery"]
        if len(d) < max(need, short):
            raise _Insufficient
        return d[-short:].mean() / d[-long:].mean()
    return _apply(hist, run_date, ("delivery",), f)
