"""Data loading, SQLite wrapper, and market-mode date validation.

Dispatches on ``market``:
  - "spy"    → Yahoo Finance (SPY OHLC, ^VIX, ^IRX), cached in market_data_master_v2.parquet
  - "bova11" → B3 COTAHIST parquet (data/B3/bova11_backtest.parquet)
  - "petr4"  → B3 COTAHIST parquet (data/B3/petr4_backtest.parquet)

All loaders return the same schema:
    underlying_open, underlying_high, underlying_low, underlying_close,
    vix_close, risk_free_rate
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from straddle.params import RISK_FREE_RATE_DEFAULT


def load_market_data(
    start_date: str,
    end_date: str,
    market: str = "spy",
    cache_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Load OHLC, implied-vol proxy, and risk-free rate for the selected market.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date:   Backtest end date (YYYY-MM-DD).
        market:     "spy" | "bova11" | "petr4".
        cache_dir:  Directory for the SPY parquet cache (ignored for B3).

    Returns:
        DataFrame indexed by date with columns:
        ``underlying_open``, ``underlying_high``, ``underlying_low``,
        ``underlying_close``, ``vix_close``, ``risk_free_rate``.
    """
    if market in ("bova11", "petr4"):
        return _load_b3_from_parquet(market, start_date, end_date, cache_dir)
    return _load_spy_from_yahoo(start_date, end_date, cache_dir)


# ── SPY loader (Yahoo Finance) ───────────────────────────────────────────

def _load_spy_from_yahoo(
    start_date: str,
    end_date: str,
    cache_dir: Optional[str] = None,
) -> pd.DataFrame:
    if cache_dir is None:
        cache_dir = str(Path(__file__).resolve().parent.parent.parent / "data")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    # v2 cache uses generic underlying_* column names
    cache_path = Path(cache_dir) / "market_data_master_v2.parquet"

    master_df = pd.DataFrame()
    if cache_path.exists():
        master_df = pd.read_parquet(cache_path)
        master_df.index = pd.to_datetime(master_df.index)

    req_start = pd.Timestamp(start_date) - pd.DateOffset(days=90)
    req_end = pd.Timestamp(end_date)

    needs_download = False
    download_start = req_start
    download_end = req_end

    if master_df.empty:
        needs_download = True
    else:
        cache_min = master_df.index.min()
        cache_max = master_df.index.max()

        if req_start >= cache_min and req_end <= cache_max:
            candidate = master_df.loc[req_start:req_end]
            if not candidate.empty:
                max_gap = candidate.index.to_series().diff().max()
                if pd.isna(max_gap) or max_gap <= pd.Timedelta(days=7):
                    return candidate.copy()

        needs_download = True
        download_start = min(req_start, cache_min)
        download_end = max(req_end, cache_max)

    if needs_download:
        tickers = ["SPY", "^VIX", "^IRX"]
        yf_end = (download_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        raw = yf.download(
            tickers,
            start=download_start.strftime("%Y-%m-%d"),
            end=yf_end,
            auto_adjust=False,
            progress=False,
        )
        if not raw.empty:
            if isinstance(raw.columns, pd.MultiIndex):
                spy_raw = raw.xs("SPY", axis=1, level=1)
                vix_raw = raw.xs("^VIX", axis=1, level=1)
                irx_raw = raw.xs("^IRX", axis=1, level=1)
            else:
                spy_raw = vix_raw = irx_raw = raw

            new_data = pd.DataFrame({
                "underlying_open":  spy_raw["Open"],
                "underlying_high":  spy_raw["High"],
                "underlying_low":   spy_raw["Low"],
                "underlying_close": spy_raw["Close"],
                "vix_close":        vix_raw["Close"],
                "risk_free_rate":   irx_raw["Close"] / 100.0,
            })
            new_data.index = pd.to_datetime(new_data.index).tz_localize(None)

            master_df = pd.concat([master_df, new_data])
            master_df = master_df[~master_df.index.duplicated(keep="last")].sort_index()
            master_df["risk_free_rate"] = (
                master_df["risk_free_rate"].ffill().bfill().fillna(RISK_FREE_RATE_DEFAULT)
            )
            master_df = master_df.dropna(subset=["underlying_close", "vix_close"])
            master_df.to_parquet(cache_path)

    return master_df.loc[req_start:req_end].copy()


# ── B3 loader (pre-built parquet) ────────────────────────────────────────

def _load_b3_from_parquet(
    market: str,
    start_date: str,
    end_date: str,
    cache_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Load pre-built COTAHIST backtest parquet for BOVA11 or PETR4.

    The parquet is produced by scripts/build_b3_parquets.py and already
    has the generic underlying_* column schema expected by the engine.

    A 90-day buffer is prepended (matching the SPY loader) so DTE
    calculations at the start of the backtest window work correctly.
    """
    if cache_dir is None:
        cache_dir = str(Path(__file__).resolve().parent.parent.parent / "data" / "B3")
    parquet_path = Path(cache_dir) / f"{market}_backtest.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"B3 backtest parquet not found: {parquet_path}\n"
            f"Run: python scripts/build_b3_parquets.py"
        )

    df = pd.read_parquet(parquet_path)
    df.index = pd.to_datetime(df.index)

    # Validate coverage
    req_start = pd.Timestamp(start_date) - pd.DateOffset(days=90)
    req_end = pd.Timestamp(end_date)
    data_start = df.index.min()
    data_end = df.index.max()

    if req_end > data_end:
        print(
            f"[{market.upper()}] WARNING: end_date {req_end.date()} is after parquet "
            f"coverage ({data_end.date()}). Backtest will stop at {data_end.date()}."
        )
        req_end = data_end

    if req_start < data_start:
        print(
            f"[{market.upper()}] WARNING: start_date buffer {req_start.date()} "
            f"predates parquet coverage ({data_start.date()}). "
            f"Using parquet start as the buffer boundary."
        )
        req_start = data_start

    slice_df = df.loc[req_start:req_end].copy()

    # Forward-fill any gaps in vix_close (ATM IV) and risk_free_rate.
    # vix_close has gaps in thin early years (e.g. BOVA11 pre-2017); ffill
    # carries the last known IV forward which is the best available estimate.
    if "vix_close" in slice_df.columns:
        slice_df["vix_close"] = slice_df["vix_close"].ffill().bfill()
        # B3 vix_close is stored as a decimal fraction (e.g. 0.37 = 37% IV).
        # SPY's VIX comes from Yahoo as percentage points (e.g. 37 = 37% IV).
        # Multiply by 100 so both markets use the same "VIX index" scale.
        # This fixes: VIX regime classification, VIX entry filter, VIX chart,
        # and synthetic engine pricing (sigma = vix_d / 100 = correct annualised vol).
        slice_df["vix_close"] = slice_df["vix_close"] * 100.0
    if "risk_free_rate" in slice_df.columns:
        slice_df["risk_free_rate"] = (
            slice_df["risk_free_rate"].ffill().bfill().fillna(RISK_FREE_RATE_DEFAULT)
        )

    return slice_df


# ── Market-mode date guardrail ───────────────────────────────────────────

_DB_FIRST = pd.Timestamp("2008-01-02")
_DB_FIRST_B3 = {"bova11": pd.Timestamp("2015-01-02"), "petr4": pd.Timestamp("2010-01-04")}
_DB_LAST_FALLBACK = pd.Timestamp("2025-12-12")
_DB_LAST_CACHE: dict[str, pd.Timestamp] = {}


def _db_coverage_end(db_path: Optional[str] = None) -> pd.Timestamp:
    """Return the latest date present in the options DB."""
    if db_path is None:
        db_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "Spy Options Database.db"
        )
    if db_path in _DB_LAST_CACHE:
        return _DB_LAST_CACHE[db_path]

    last = _DB_LAST_FALLBACK
    try:
        import sqlite3
        if Path(db_path).exists():
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                cur = con.execute("SELECT MAX(date) FROM options_data")
                row = cur.fetchone()
            finally:
                con.close()
            if row and row[0]:
                last = pd.Timestamp(row[0])
    except Exception:
        pass

    _DB_LAST_CACHE[db_path] = last
    return last


def validate_market_mode_dates(
    start_date: str,
    end_date: str,
    db_path: Optional[str] = None,
    market: str = "spy",
) -> None:
    """Validate date range against DB coverage for market mode.

    For B3 markets, checks against BVMF-specific start dates.
    Raises ValueError if start_date predates DB coverage.
    Prints a warning if end_date exceeds DB coverage (MarketEngine falls back to synthetic).
    """
    _start = pd.Timestamp(start_date)
    _end = pd.Timestamp(end_date)
    db_last = _db_coverage_end(db_path)

    # Determine the DB first date for the market
    if market in _DB_FIRST_B3:
        db_first = _DB_FIRST_B3[market]
    else:
        db_first = _DB_FIRST

    if _start < db_first:
        raise ValueError(
            f"Market mode ({market}): start_date {_start.date()} is before DB "
            f"coverage ({db_first.date()}). Use mode='synthetic' or set "
            f"start_date >= {db_first.date()}."
        )

    if _end > db_last:
        print(
            f"[MarketEngine/{market}] WARNING: end_date {_end.date()} is after DB "
            f"coverage ({db_last.date()}). Pricing will fall back to synthetic "
            f"for all dates beyond {db_last.date()}."
        )
