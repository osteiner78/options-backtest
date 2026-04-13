"""Data loading, SQLite wrapper, and market-mode date validation.

Loads SPY OHLC (unadjusted), VIX, and risk-free rate from Yahoo Finance.
Caches to a local parquet file so repeated runs don't re-download.
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from straddle.params import RISK_FREE_RATE_DEFAULT


def load_market_data(
    start_date: str,
    end_date: str,
    cache_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Load SPY OHLC (unadjusted), VIX, and risk-free rate into a single aligned DataFrame.

    Maintains a master cache file ('market_data_master.parquet') and only downloads
    missing date ranges from Yahoo Finance.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        cache_dir: Directory for parquet cache. Defaults to ``data/``.

    Returns:
        DataFrame indexed by date with columns:
        ``spy_open``, ``spy_high``, ``spy_low``, ``spy_close``,
        ``vix_close``, ``risk_free_rate``.
    """
    # ── Path Setup ───────────────────────────────────────────────────────
    if cache_dir is None:
        cache_dir = str(Path(__file__).resolve().parent.parent.parent / "data")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_dir) / "market_data_master.parquet"

    # ── Load Cache ───────────────────────────────────────────────────────
    master_df = pd.DataFrame()
    if cache_path.exists():
        master_df = pd.read_parquet(cache_path)
        master_df.index = pd.to_datetime(master_df.index)

    # ── Determine Missing Ranges ─────────────────────────────────────────
    # We need a 90-day buffer before start_date for DTE calculations
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

        # If the requested range is fully within the cache bounds, check that
        # the slice is actually contiguous — disjointed runs (e.g. 2020 + 2022
        # cached separately) produce a false "within bounds" hit with a silent
        # data hole in the middle.
        if req_start >= cache_min and req_end <= cache_max:
            candidate = master_df.loc[req_start:req_end]
            if not candidate.empty:
                max_gap = candidate.index.to_series().diff().max()
                if pd.isna(max_gap) or max_gap <= pd.Timedelta(days=7):
                    return candidate.copy()
            # Gap detected — fall through to re-download the full range.

        # Determine the expanded range needed, merging with whatever is cached.
        needs_download = True
        download_start = min(req_start, cache_min)
        download_end = max(req_end, cache_max)

    # ── Fetch Missing Data ───────────────────────────────────────────────
    if needs_download:
        tickers = ["SPY", "^VIX", "^IRX"]
        # yfinance download is end-exclusive usually, so we add a day to end
        yf_end = (download_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        
        raw = yf.download(
            tickers, 
            start=download_start.strftime("%Y-%m-%d"), 
            end=yf_end, 
            auto_adjust=False, 
            progress=False
        )
        
        if not raw.empty:
            # Extract and align
            if isinstance(raw.columns, pd.MultiIndex):
                spy_raw = raw.xs("SPY", axis=1, level=1)
                vix_raw = raw.xs("^VIX", axis=1, level=1)
                irx_raw = raw.xs("^IRX", axis=1, level=1)
            else:
                spy_raw = raw
                vix_raw = raw
                irx_raw = raw

            new_data = pd.DataFrame({
                "spy_open": spy_raw["Open"],
                "spy_high": spy_raw["High"],
                "spy_low": spy_raw["Low"],
                "spy_close": spy_raw["Close"],
                "vix_close": vix_raw["Close"],
                "risk_free_rate": irx_raw["Close"] / 100.0,
            })
            new_data.index = pd.to_datetime(new_data.index).tz_localize(None)

            # Merge with master and remove duplicates
            master_df = pd.concat([master_df, new_data])
            master_df = master_df[~master_df.index.duplicated(keep='last')].sort_index()

            # Post-processing (ffill RF rate)
            master_df["risk_free_rate"] = master_df["risk_free_rate"].ffill().bfill().fillna(RISK_FREE_RATE_DEFAULT)
            master_df = master_df.dropna(subset=["spy_close", "vix_close"])

            # Save updated master
            master_df.to_parquet(cache_path)

    # ── Final Slice ──────────────────────────────────────────────────────
    # Re-slice to the exact range requested (including buffer)
    return master_df.loc[req_start:req_end].copy()


# ── Market-mode date guardrail ───────────────────────────────────────────

_DB_FIRST = pd.Timestamp("2008-01-02")
_DB_LAST = pd.Timestamp("2025-12-12")


def validate_market_mode_dates(start_date: str, end_date: str) -> None:
    """Validate date range against DB coverage for market mode.

    Raises ValueError if start_date predates the DB (no data at all for that
    period). Prints a warning — but does NOT raise — if end_date exceeds DB
    coverage: MarketEngine already falls back to SyntheticEngine per-leg for
    missing rows, so the backtest continues with synthetic pricing for those
    dates.
    """
    _start = pd.Timestamp(start_date)
    _end = pd.Timestamp(end_date)

    if _start < _DB_FIRST:
        raise ValueError(
            f"Market mode: start_date {_start.date()} is before DB coverage "
            f"({_DB_FIRST.date()}). Use mode='synthetic' or set start_date >= "
            f"{_DB_FIRST.date()}."
        )

    if _end > _DB_LAST:
        print(
            f"[MarketEngine] WARNING: end_date {_end.date()} is after DB coverage "
            f"({_DB_LAST.date()}). Pricing will fall back to synthetic (Black-Scholes) "
            f"for all dates beyond {_DB_LAST.date()}."
        )
