"""Phase 3: Recompute IVs and deltas using daily CDI rates (instead of flat r=12%).

Reads options from b3_options_rb3.db, gets S and r from backtest parquets,
recomputes implied_volatility_cdi and delta_cdi columns.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm
from joblib import Parallel, delayed

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "B3" / "b3_options_rb3.db"
BOVA_PARQUET = ROOT / "data" / "B3" / "bova11_backtest.parquet"
PETR_PARQUET = ROOT / "data" / "B3" / "petr4_backtest.parquet"
N_JOBS = -1  # use all cores


def bsm_price(S, K, T, r, sigma, opt_type):
    if T <= 0 or sigma <= 0 or S <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt_type == "call":
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def bsm_delta(S, K, T, r, sigma, opt_type):
    if T <= 0 or sigma <= 0 or S <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    if opt_type == "call":
        return float(norm.cdf(d1))
    return float(-norm.cdf(-d1))


def implied_vol(price, S, K, T, r, opt_type):
    if T <= 0 or K <= 0 or S <= 0 or price <= 0:
        return np.nan
    try:
        return float(
            brentq(
                lambda s: bsm_price(S, K, T, r, s, opt_type) - price,
                0.001,
                10.0,
                maxiter=100,
            )
        )
    except (ValueError, RuntimeError):
        return np.nan


def _process_row(args):
    idx, date, expiration, opt_type, strike, mark, S, r = args
    if pd.isna(S) or S <= 0 or pd.isna(r) or mark is None or mark <= 0:
        return idx, np.nan, np.nan
    T = (pd.Timestamp(expiration) - pd.Timestamp(date)).days / 365.0
    if T <= 0:
        return idx, np.nan, np.nan
    iv = implied_vol(mark, S, strike, T, r, opt_type)
    if np.isnan(iv):
        return idx, np.nan, np.nan
    delta = bsm_delta(S, strike, T, r, iv, opt_type)
    return idx, iv, delta


def build_lookups():
    bova = pd.read_parquet(BOVA_PARQUET)
    petr = pd.read_parquet(PETR_PARQUET)

    # Build (underlying, date_str) → underlying_close
    s_lookup = {}
    for df, und in [(bova, "bova11"), (petr, "petr4")]:
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            s_lookup[(und, date_str)] = float(row["underlying_close"])

    # CDI rates are the same for both (just use bova's)
    r_lookup = {}
    for idx, row in bova.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        r_lookup[date_str] = float(row["risk_free_rate"])

    return s_lookup, r_lookup


def main():
    print("Building S and r lookups from backtest parquets...")
    s_lookup, r_lookup = build_lookups()
    print(f"  S lookup: {len(s_lookup):,} entries")
    print(f"  r lookup: {len(r_lookup):,} entries")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Add new columns if they don't exist
    existing = {r[1] for r in conn.execute("PRAGMA table_info(options_data)")}
    for col in ("implied_volatility_cdi", "delta_cdi"):
        if col not in existing:
            conn.execute(f"ALTER TABLE options_data ADD COLUMN {col} REAL")
            conn.commit()
            print(f"  Added column: {col}")

    for und in ("bova11", "petr4"):
        print(f"\nProcessing {und}...")
        rows = conn.execute(
            "SELECT rowid, date, expiration, type, strike, mark "
            "FROM options_data WHERE underlying = ? AND mark > 0",
            (und,),
        ).fetchall()

        total = len(rows)
        print(f"  {total:,} rows to process")

        # Build args for parallel processing
        args_list = []
        missing_s = 0
        missing_r = 0
        for row in rows:
            date_str = row["date"]
            S = s_lookup.get((und, date_str))
            r = r_lookup.get(date_str)
            if S is None:
                missing_s += 1
                continue
            if r is None:
                missing_r += 1
                continue
            args_list.append(
                (
                    row["rowid"],
                    row["date"],
                    row["expiration"],
                    row["type"],
                    row["strike"],
                    row["mark"],
                    S,
                    r,
                )
            )

        if missing_s:
            print(f"  Missing S: {missing_s:,} rows")
        if missing_r:
            print(f"  Missing r: {missing_r:,} rows")
        print(f"  Processing {len(args_list):,} rows with {N_JOBS} workers...")

        results = Parallel(n_jobs=N_JOBS, verbose=10)(
            delayed(_process_row)(args) for args in args_list
        )

        # Batch UPDATE
        updates = [(iv, delta, rowid) for rowid, iv, delta in results if not np.isnan(iv)]
        print(f"  Valid IVs computed: {len(updates):,} / {len(args_list):,}")

        batch_size = 5000
        for i in range(0, len(updates), batch_size):
            batch = updates[i : i + batch_size]
            conn.executemany(
                "UPDATE options_data SET implied_volatility_cdi = ?, delta_cdi = ? WHERE rowid = ?",
                batch,
            )
            if (i + batch_size) % 50000 == 0:
                conn.commit()
                print(f"    batch {i + batch_size:,} committed")

        conn.commit()
        print(f"  {und}: {len(updates):,} rows updated with CDI-based IVs/deltas")

    conn.close()
    print(f"\nDone. DB updated at {DB_PATH}")


if __name__ == "__main__":
    main()
