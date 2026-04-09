"""Data loading, SQLite wrapper, and market-mode date validation.

Loads SPY OHLC (unadjusted), VIX, and risk-free rate from Yahoo Finance.
Caches to a local parquet file so repeated runs don't re-download.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf


def _extract_col(raw: pd.DataFrame, col: str) -> pd.Series:
    """Handle both flat and MultiIndex column structures (yfinance >= 0.2)."""
    series = raw[col]
    return series.iloc[:, 0] if isinstance(series, pd.DataFrame) else series


def load_market_data(
    start_date: str,
    end_date: str,
    cache_dir: str | None = None,
) -> pd.DataFrame:
    """Load SPY OHLC (unadjusted), VIX, and risk-free rate into a single aligned DataFrame.

    SPY OHLC uses auto_adjust=False so that prices match the actual market levels
    at each date -- the same price scale used by the options DB and by exchange-listed
    strikes.  Dividend-adjusted prices (yfinance default) are ~20% lower for 2015
    data and would cause synthetic BS strikes to be ~20% too low relative to real
    option chains.  VIX and IRX are index/yield series with no dividends; auto_adjust
    is a no-op for them.

    A 90-day buffer before ``start_date`` is fetched so that DTE calculations
    are available for the first entry.

    Results are cached to a parquet file keyed by the (start, end) range so
    that repeated runs don't re-download from Yahoo Finance.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        cache_dir: Directory for parquet cache. Defaults to ``data/`` next to
            this module.

    Returns:
        DataFrame indexed by date with columns:
        ``spy_open``, ``spy_high``, ``spy_low``, ``spy_close``,
        ``vix_close``, ``risk_free_rate``.
    """
    buffer_start = (pd.Timestamp(start_date) - pd.DateOffset(days=90)).strftime(
        "%Y-%m-%d"
    )

    # ── Parquet cache ────────────────────────────────────────────────────
    if cache_dir is None:
        cache_dir = str(Path(__file__).resolve().parent.parent.parent / "data")
    cache_path = Path(cache_dir) / f"market_data_{start_date}_{end_date}.parquet"

    if cache_path.exists():
        data = pd.read_parquet(cache_path)
        data.index = pd.to_datetime(data.index)
        return data

    # ── Fetch from Yahoo Finance ─────────────────────────────────────────
    spy_raw = yf.download(
        "SPY", start=buffer_start, end=end_date, auto_adjust=False, progress=False
    )
    vix_raw = yf.download(
        "^VIX", start=buffer_start, end=end_date, auto_adjust=True, progress=False
    )
    irx_raw = yf.download(
        "^IRX", start=buffer_start, end=end_date, auto_adjust=True, progress=False
    )

    spy_raw.index = pd.to_datetime(spy_raw.index).tz_localize(None)
    irx = _extract_col(irx_raw, "Close") / 100.0

    data = pd.DataFrame(
        {
            "spy_open": _extract_col(spy_raw, "Open"),
            "spy_high": _extract_col(spy_raw, "High"),
            "spy_low": _extract_col(spy_raw, "Low"),
            "spy_close": _extract_col(spy_raw, "Close"),
        }
    )
    data["vix_close"] = _extract_col(vix_raw, "Close")
    data["risk_free_rate"] = irx
    data.index = pd.to_datetime(data.index).tz_localize(None)
    data["risk_free_rate"] = data["risk_free_rate"].ffill().bfill().fillna(0.045)
    data = data.dropna(subset=["spy_close", "vix_close"])

    # ── Write cache ──────────────────────────────────────────────────────
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    data.to_parquet(cache_path)

    return data


# ── Market-mode date guardrail ───────────────────────────────────────────
# options_data covers 2008-01-02 -> 2025-12-12. Backtesting outside this
# window in market mode silently falls back to synthetic for every trade,
# making results misleading. Raise early instead.

_DB_FIRST = pd.Timestamp("2008-01-02")
_DB_LAST = pd.Timestamp("2025-12-12")


def validate_market_mode_dates(start_date: str, end_date: str) -> None:
    """Raise ValueError if the requested date range is outside DB coverage.

    The SQLite options database covers 2008-01-02 through 2025-12-12.
    Running in market mode outside this window silently falls back to
    synthetic pricing for every trade, making results misleading.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).

    Raises:
        ValueError: If start_date is before DB coverage or end_date is after.
    """
    _start = pd.Timestamp(start_date)
    _end = pd.Timestamp(end_date)
    errors = []
    if _start < _DB_FIRST:
        errors.append(
            f"start_date {_start.date()} is before DB coverage ({_DB_FIRST.date()})"
        )
    if _end > _DB_LAST:
        errors.append(
            f"end_date {_end.date()} is after DB coverage ({_DB_LAST.date()})"
        )
    if errors:
        raise ValueError(
            "Market mode date range out of bounds:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\nSwitch to mode='synthetic' or adjust start_date / end_date."
        )
