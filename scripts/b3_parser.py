"""B3 COTAHIST options parser — extracted from research notebook.

All parsing, Black-Scholes, and data-building functions live here so
build_b3_parquets.py and build_b3_options_db.py can share them without
touching the notebook or production src/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

import warnings
warnings.filterwarnings("ignore")


# ── Price scaling ─────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> float:
    raw = raw.strip()
    if not raw or raw == "0" * len(raw):
        return np.nan
    try:
        return int(raw) / 100.0
    except ValueError:
        return np.nan


def _parse_volume(raw: str) -> float:
    raw = raw.strip()
    if not raw or raw == "0" * len(raw):
        return np.nan
    try:
        return int(raw) / 100.0
    except ValueError:
        return np.nan


def _parse_qty(raw: str) -> int:
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        return 0


# ── Black-Scholes utilities ───────────────────────────────────────────────────

def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if option_type == "call" else (K - S))
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(
    market_price: float,
    S: float, K: float, T: float, r: float, option_type: str,
    low: float = 1e-6, high: float = 10.0,
) -> float:
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return np.nan
    try:
        intrinsic = max(0.0, (S - K) if option_type == "call" else (K - S))
        if market_price <= intrinsic:
            return np.nan
        f = lambda sigma: bs_price(S, K, T, r, sigma, option_type) - market_price
        if f(low) * f(high) > 0:
            return np.nan
        return brentq(f, low, high, xtol=1e-6, maxiter=200)
    except Exception:
        return np.nan


def compute_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> dict:
    if T <= 0 or sigma <= 0 or S <= 0:
        return {"delta": np.nan, "gamma": np.nan, "theta": np.nan, "vega": np.nan}
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    pdf_d1 = norm.pdf(d1)
    gamma = pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * pdf_d1 * np.sqrt(T) / 100
    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * pdf_d1 * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * pdf_d1 * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


# ── CDI rates from BCB ────────────────────────────────────────────────────────

def fetch_cdi_rates(start: str, end: Optional[str] = None) -> pd.DataFrame:
    """Fetch daily CDI rates from BCB (series 12) as annualised rates.

    Returns DataFrame with columns: date (datetime64), risk_free_rate (float).
    Annualisation uses the Brazilian 252 business-day convention:
        annualized = (1 + daily_cdi_pct/100)^252 - 1

    BCB API limits daily series queries to a 10-year window; this function
    chunks automatically so any date range works.
    """
    from bcb import sgs

    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end) if end else pd.Timestamp.today()

    # Split into ≤9-year chunks to stay safely under the 10-year API limit
    chunks = []
    chunk_start = start_ts
    while chunk_start <= end_ts:
        chunk_end = min(chunk_start + pd.DateOffset(years=9), end_ts)
        raw = sgs.get(
            {"cdi": 12},
            start=chunk_start.strftime("%Y-%m-%d"),
            end=chunk_end.strftime("%Y-%m-%d"),
        )
        if not raw.empty:
            chunks.append(raw)
        chunk_start = chunk_end + pd.Timedelta(days=1)

    if not chunks:
        return pd.DataFrame(columns=["date", "risk_free_rate"])

    combined = pd.concat(chunks)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    df = combined.reset_index().rename(columns={"Date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df["risk_free_rate"] = (1 + df["cdi"] / 100) ** 252 - 1
    return df[["date", "risk_free_rate"]]


# ── COTAHIST parsers ──────────────────────────────────────────────────────────

def extract_equity_prices(filepath: str | Path, tickers: list[str]) -> pd.DataFrame:
    """Extract daily close prices for equity tickers from a COTAHIST file.

    Returns DataFrame with columns: date, underlying, equity_ticker, underlying_price.
    """
    filepath = Path(filepath)
    rows = []
    tickers_upper = [t.upper() for t in tickers]

    with open(filepath, encoding="latin-1") as f:
        for line in f:
            if len(line) < 245:
                continue
            if line[0:2] != "01":
                continue
            if line[10:12].strip() not in ("02", "14"):
                continue
            if line[24:27].strip() != "010":
                continue
            ticker = line[12:24].strip().upper()
            if ticker not in tickers_upper:
                continue
            close = _parse_price(line[108:121])
            if pd.isna(close) or close <= 0:
                continue
            rows.append({
                "date": pd.to_datetime(line[2:10], format="%Y%m%d"),
                "underlying": line[27:39].strip().upper(),
                "equity_ticker": ticker,
                "underlying_price": close,
            })

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .drop_duplicates(["date", "equity_ticker"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def extract_equity_ohlc(filepath: str | Path, tickers: list[str]) -> pd.DataFrame:
    """Extract daily OHLC for equity tickers from a COTAHIST file.

    Returns DataFrame with columns: date, equity_ticker, open, high, low, close.
    """
    filepath = Path(filepath)
    rows = []
    tickers_upper = [t.upper() for t in tickers]

    with open(filepath, encoding="latin-1") as f:
        for line in f:
            if len(line) < 245:
                continue
            if line[0:2] != "01":
                continue
            if line[10:12].strip() not in ("02", "14"):
                continue
            if line[24:27].strip() != "010":
                continue
            ticker = line[12:24].strip().upper()
            if ticker not in tickers_upper:
                continue
            open_ = _parse_price(line[56:69])
            high = _parse_price(line[69:82])
            low = _parse_price(line[82:95])
            close = _parse_price(line[108:121])
            if pd.isna(close) or close <= 0:
                continue
            rows.append({
                "date": pd.to_datetime(line[2:10], format="%Y%m%d"),
                "equity_ticker": ticker,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            })

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .drop_duplicates(["date", "equity_ticker"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def parse_cotahist(
    filepath: str | Path,
    underlying_names: Optional[list[str]] = None,
    option_types: Optional[list[str]] = None,
    min_trades: int = 10,
    min_volume: float = 1000.0,
    min_open_interest: int = 0,
    min_price: float = 0.01,
    max_moneyness: float = 0.30,
    min_dte: int = 7,
    max_dte: int = 90,
    compute_greeks_flag: bool = True,
    risk_free_rate: float = 0.1075,
    risk_free_rates: Optional[pd.DataFrame] = None,
    underlying_prices: Optional[pd.DataFrame] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Parse B3 COTAHIST fixed-width file and return a clean options DataFrame."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    rows = []
    skipped_filter = 0
    skipped_parse = 0
    total_options = 0

    if verbose:
        print(f"  Parsing {filepath.name}...", flush=True)

    with open(filepath, encoding="latin-1") as f:
        for line in f:
            line = line.rstrip("\n")
            if len(line) < 245:
                continue
            if line[0:2] != "01":
                continue

            bdi = line[10:12].strip()
            if bdi not in ("78", "82"):
                continue

            option_type = "call" if bdi == "78" else "put"
            total_options += 1

            if option_types and option_type not in option_types:
                skipped_filter += 1
                continue

            nomres = line[27:39].strip().upper()
            if underlying_names:
                if not any(u.upper() in nomres for u in underlying_names):
                    skipped_filter += 1
                    continue

            clean_nomres = nomres.split()[0] if " " in nomres else nomres
            clean_nomres = clean_nomres.split("/")[0] if "/" in clean_nomres else clean_nomres
            if clean_nomres.startswith("PETR"):
                clean_nomres = "PETROBRAS"
            elif clean_nomres.startswith("BOVA") or clean_nomres == "ISHARES":
                clean_nomres = "ISHARES BOVA"

            try:
                close = _parse_price(line[108:121])
                strike = _parse_price(line[188:201])
                bid = _parse_price(line[121:134])
                ask = _parse_price(line[134:147])
                open_ = _parse_price(line[56:69])
                high = _parse_price(line[69:82])
                low = _parse_price(line[82:95])
                avg = _parse_price(line[95:108])
                volume = _parse_volume(line[170:188])
                qty = _parse_qty(line[152:170])
                n_trades = int(line[147:152].strip() or 0)
                date = pd.to_datetime(line[2:10], format="%Y%m%d")
                expiry = pd.to_datetime(line[202:210], format="%Y%m%d")
                ticker = line[12:24].strip()
                isin = line[230:242].strip()
            except Exception:
                skipped_parse += 1
                continue

            if pd.isna(close) or pd.isna(strike) or close <= 0 or strike <= 0:
                skipped_filter += 1
                continue

            dte = (expiry - date).days
            if dte < min_dte or dte > max_dte:
                skipped_filter += 1
                continue

            if n_trades < min_trades:
                skipped_filter += 1
                continue
            if (not pd.isna(volume)) and volume < min_volume:
                skipped_filter += 1
                continue
            if qty < min_open_interest:
                skipped_filter += 1
                continue
            if close < min_price:
                skipped_filter += 1
                continue

            if (not pd.isna(bid)) and (not pd.isna(ask)) and bid > 0 and ask > 0:
                mid_price = (bid + ask) / 2
                spread = ask - bid
                spread_pct = spread / mid_price if mid_price > 0 else np.nan
            else:
                mid_price = close
                spread = np.nan
                spread_pct = np.nan

            rows.append({
                "date": date, "ticker": ticker, "underlying": clean_nomres,
                "isin": isin, "option_type": option_type, "strike": strike,
                "expiry": expiry, "dte": dte, "close": close, "open": open_,
                "high": high, "low": low, "avg": avg, "mid_price": mid_price,
                "bid": bid, "ask": ask, "spread": spread, "spread_pct": spread_pct,
                "n_trades": n_trades, "qty": qty, "volume_brl": volume,
            })

    if not rows:
        if verbose:
            print("  No records matched the filters.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values(["date", "underlying", "option_type", "expiry", "strike"])
    df = df.reset_index(drop=True)

    if compute_greeks_flag:
        if underlying_prices is not None:
            df = df.merge(underlying_prices, on=["date", "underlying"], how="left")
        else:
            df["underlying_price"] = np.nan

        if "underlying_price" in df.columns and df["underlying_price"].notna().any():
            price_missing = df["underlying_price"].isna()
            if price_missing.any() and verbose:
                missing = sorted(df.loc[price_missing, "underlying"].unique())
                print(f"  WARNING: {price_missing.sum():,} records dropped — no underlying_price for: {missing}")
            df = df[~price_missing].copy()

            moneyness = (df["underlying_price"] - df["strike"]).abs() / df["underlying_price"]
            before = len(df)
            df = df[moneyness <= max_moneyness].copy()
            if verbose and len(df) < before:
                print(f"  Moneyness filter removed {before - len(df):,} deep OTM/ITM records.")

        if risk_free_rates is not None:
            df = df.merge(risk_free_rates, on="date", how="left")
            n_missing = df["risk_free_rate"].isna().sum()
            if n_missing > 0:
                if verbose:
                    print(f"  WARNING: {n_missing:,} records have no CDI rate — filling with fallback {risk_free_rate:.4f}")
                df["risk_free_rate"] = df["risk_free_rate"].fillna(risk_free_rate)
        else:
            df["risk_free_rate"] = risk_free_rate

        def _row_greeks(row):
            S = row.get("underlying_price", np.nan)
            r = row["risk_free_rate"]
            if pd.isna(S) or S <= 0:
                return pd.Series({"iv": np.nan, "delta": np.nan, "gamma": np.nan, "theta": np.nan, "vega": np.nan})
            T = row["dte"] / 365.0
            iv = implied_vol(row["mid_price"], S, row["strike"], T, r, row["option_type"])
            if pd.isna(iv):
                return pd.Series({"iv": np.nan, "delta": np.nan, "gamma": np.nan, "theta": np.nan, "vega": np.nan})
            g = compute_greeks(S, row["strike"], T, r, iv, row["option_type"])
            return pd.Series({"iv": iv, **g})

        if verbose:
            print(f"  Computing IV and Greeks for {len(df):,} records...", flush=True)
        greeks_df = df.apply(_row_greeks, axis=1)
        df = pd.concat([df, greeks_df], axis=1)

    if verbose:
        print(f"  → {len(df):,} records  "
              f"(calls: {(df['option_type']=='call').sum():,}  "
              f"puts: {(df['option_type']=='put').sum():,}  "
              f"IV ok: {df['iv'].notna().sum() if 'iv' in df.columns else 'n/a':,})")

    return df


# ── ATM IV proxy (VIX equivalent) ─────────────────────────────────────────────

def compute_daily_atm_iv(
    options_df: pd.DataFrame,
    dte_min: int = 20,
    dte_max: int = 45,
    moneyness_max: float = 0.05,
) -> pd.Series:
    """Volume-weighted average IV of near-ATM options in [dte_min, dte_max].

    Returns a Series indexed by date — used as vix_close proxy.
    """
    if options_df.empty or "iv" not in options_df.columns:
        return pd.Series(dtype=float, name="vix_close")

    mask = (
        (options_df["dte"] >= dte_min)
        & (options_df["dte"] <= dte_max)
        & (
            (options_df["underlying_price"] - options_df["strike"]).abs()
            / options_df["underlying_price"]
            <= moneyness_max
        )
        & options_df["iv"].notna()
    )
    atm = options_df[mask]
    if atm.empty:
        return pd.Series(dtype=float, name="vix_close")

    def wavg(g):
        w = g["volume_brl"].fillna(1.0).clip(lower=1.0)
        return np.average(g["iv"], weights=w)

    return atm.groupby("date").apply(wavg).rename("vix_close")


# ── Multi-year backtest DataFrame builder ─────────────────────────────────────

def build_backtest_df(
    data_dir: str | Path,
    equity_ticker: str,
    underlying_name_filter: list[str],
    cdi_rates: pd.DataFrame,
    min_trades: int = 5,
    dte_min: int = 20,
    dte_max: int = 45,
    atm_moneyness: float = 0.05,
    verbose: bool = True,
) -> pd.DataFrame:
    """Build a backtest-ready DataFrame from all COTAHIST_A*.TXT files in data_dir.

    Returns DataFrame indexed by date with columns:
        underlying_open, underlying_high, underlying_low, underlying_close,
        vix_close, risk_free_rate
    """
    data_dir = Path(data_dir)
    files = sorted(data_dir.glob("COTAHIST_A*.TXT"))
    if not files:
        raise FileNotFoundError(f"No COTAHIST_A*.TXT files found in {data_dir}")

    ohlc_parts = []
    opts_parts = []

    for fp in files:
        if verbose:
            print(f"  {fp.name} ...", end=" ", flush=True)

        ohlc = extract_equity_ohlc(fp, [equity_ticker])
        if not ohlc.empty:
            ohlc_parts.append(ohlc)

        eq_prices = extract_equity_prices(fp, [equity_ticker])

        opts = parse_cotahist(
            fp,
            underlying_names=underlying_name_filter,
            min_trades=min_trades,
            min_volume=1_000,
            min_price=0.01,
            max_moneyness=0.30,
            min_dte=dte_min,
            max_dte=dte_max,
            compute_greeks_flag=True,
            risk_free_rates=cdi_rates,
            underlying_prices=eq_prices,
            verbose=False,
        )
        if not opts.empty:
            opts_parts.append(opts)

        if verbose:
            n_days = ohlc["date"].nunique() if not ohlc.empty else 0
            print(f"{n_days} trading days, {len(opts):,} ATM option records")

    if not ohlc_parts:
        raise ValueError(f"No OHLC data found for {equity_ticker}.")

    ohlc_all = (
        pd.concat(ohlc_parts).drop_duplicates("date").set_index("date").sort_index()
    )

    if opts_parts:
        opts_all = pd.concat(opts_parts, ignore_index=True)
        daily_iv = compute_daily_atm_iv(opts_all, dte_min=dte_min, dte_max=dte_max, moneyness_max=atm_moneyness)
    else:
        daily_iv = pd.Series(dtype=float, name="vix_close")

    result = pd.DataFrame({
        "underlying_open":  ohlc_all["open"],
        "underlying_high":  ohlc_all["high"],
        "underlying_low":   ohlc_all["low"],
        "underlying_close": ohlc_all["close"],
    })
    result = result.join(daily_iv, how="left")
    result = result.join(cdi_rates.set_index("date")[["risk_free_rate"]], how="left")

    if verbose:
        iv_cov = result["vix_close"].notna().mean()
        rfr_cov = result["risk_free_rate"].notna().mean()
        print(
            f"\n  Result: {len(result)} trading days"
            f"  |  vix_close coverage {iv_cov:.1%}"
            f"  |  CDI coverage {rfr_cov:.1%}"
        )
        print(result.tail(3))

    return result
