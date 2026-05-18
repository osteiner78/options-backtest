"""Phase 1: Full-period parity regression — rb3 vs old DB.

Runs identical backtests on both databases and saves trade-level results.
Also produces the aggregate comparison table and strike-delta distributions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import numpy as np
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "phase1_regression"

OLD_DB = "data/B3/b3_options.db"
NEW_DB = "data/B3/b3_options_rb3.db"

START = "2017-01-02"
END = "2025-12-31"


def trades_to_df(trades) -> pd.DataFrame:
    rows = []
    for t in trades:
        mtm_total = getattr(t, 'mtm_total_days', 0)
        mtm_source = getattr(t, 'mtm_source_days', 0)
        rows.append(
            {
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "exit_type": t.exit_type,
                "put_strike": t.put_strike,
                "call_strike": t.call_strike,
                "net_credit": t.net_credit,
                "pnl": t.pnl,
                "entry_dte": t.entry_dte,
                "entry_vix": t.entry_vix,
                "used_market_data": t.used_market_data,
                "entry_source": getattr(t, 'entry_source', 'unknown'),
                "exit_source": getattr(t, 'exit_source', 'unknown'),
                "mtm_source_days": mtm_source,
                "mtm_total_days": mtm_total,
                "mtm_db_pct": mtm_source / mtm_total if mtm_total > 0 else 0,
                "roll_count": t.roll_count,
                "parent_trade_num": t.parent_trade_num,
            }
        )
    return pd.DataFrame(rows)


def run_one(market: str, db_path: str, label: str) -> pd.DataFrame:
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params["start_date"] = START
    params["end_date"] = END
    params["mode"] = "market"
    params["options_db_path"] = db_path
    # Override VIX cap as plan specifies
    params["vix_entry_max"] = 35.0

    print(f"  [{label}] Loading market data ({START} → {END})...")
    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market=market,
    )

    print(f"  [{label}] Running backtest...")
    engine = make_engine(params)
    try:
        trades, _, skipped, vix_blocked = run_backtest(data, params, engine)
    finally:
        if hasattr(engine, "close"):
            engine.close()

    df = trades_to_df(trades)
    out_path = OUT / f"{market}_{label}.parquet"
    df.to_parquet(out_path)
    n_db = df["used_market_data"].sum()
    print(
        f"  [{label}] Done: {len(df)} trades, {n_db}/{len(df)} DB entries, "
        f"skipped={skipped}, vix_blocked={len(vix_blocked) if vix_blocked else 0}"
    )
    print(f"  [{label}] Saved → {out_path}")
    return df


def compare(market: str, df_old: pd.DataFrame, df_new: pd.DataFrame):
    print(f"\n{'='*70}")
    print(f"  {market.upper()} — Old DB vs rb3  ({START} → {END})")
    print(f"{'='*70}")

    for label, df in [("old DB", df_old), ("rb3", df_new)]:
        pnls = df["pnl"].dropna()
        credits = df["net_credit"]
        print(f"\n  {label}:")
        print(f"    Trades:           {len(df)}")
        print(f"    Total P&L:        R${pnls.sum():+,.2f}")
        print(f"    Mean P&L/trade:   R${pnls.mean():+,.2f}")
        print(f"    Median P&L/trade: R${pnls.median():+,.2f}")
        print(f"    Win rate:         {((pnls > 0).sum() / len(pnls) * 100):.1f}%")
        print(f"    Avg credit:       R${credits.mean():.2f}")
        print(f"    Avg DTE entry:    {df['entry_dte'].mean():.1f}")
        exits = df["exit_type"].value_counts()
        for et in ["PROFIT", "21DTE", "ROLLED", "STOP", "EXPIRY"]:
            if et in exits:
                print(f"    {et}:              {exits[et]}")

    # Aggregate delta
    pnl_old = df_old["pnl"].dropna().sum()
    pnl_new = df_new["pnl"].dropna().sum()
    delta_pnl = pnl_new - pnl_old
    print(f"\n  Δ P&L (rb3 - old):  R${delta_pnl:+,.2f}")
    if pnl_old != 0:
        print(f"  |Δ| / |old|:         {abs(delta_pnl) / abs(pnl_old) * 100:.1f}%")

    # Per-trade P&L stats
    pnl_ot = df_old["pnl"].dropna()
    pnl_nt = df_new["pnl"].dropna()
    print(f"  Δ Mean P&L:          R${pnl_nt.mean() - pnl_ot.mean():+,.2f}")
    print(f"  σ old:               R${pnl_ot.std():.2f}")
    print(f"  σ new:               R${pnl_nt.std():.2f}")

    # Strike / credit distribution
    merged = pd.merge(
        df_old[["entry_date", "put_strike", "call_strike", "net_credit"]].rename(
            columns={"put_strike": "put_old", "call_strike": "call_old", "net_credit": "credit_old"}
        ),
        df_new[["entry_date", "put_strike", "call_strike", "net_credit"]].rename(
            columns={"put_strike": "put_new", "call_strike": "call_new", "net_credit": "credit_new"}
        ),
        on="entry_date",
        how="inner",
    )
    merged["delta_put"] = merged["put_new"] - merged["put_old"]
    merged["delta_call"] = merged["call_new"] - merged["call_old"]
    merged["delta_credit"] = merged["credit_new"] - merged["credit_old"]

    n_matched = len(merged)
    print(f"\n  Matched entry-date pairs: {n_matched}")
    print(f"  Δ put strike:  mean={merged['delta_put'].mean():+.2f}, "
          f"median={merged['delta_put'].median():+.2f}, "
          f"σ={merged['delta_put'].std():.2f}")
    print(f"  Δ call strike: mean={merged['delta_call'].mean():+.2f}, "
          f"median={merged['delta_call'].median():+.2f}, "
          f"σ={merged['delta_call'].std():.2f}")
    print(f"  Δ credit:      mean={merged['delta_credit'].mean():+.2f}, "
          f"median={merged['delta_credit'].median():+.2f}, "
          f"σ={merged['delta_credit'].std():.2f}")

    # Distribution: count of non-zero strike diffs
    put_diff_nonzero = (merged["delta_put"] != 0).sum()
    call_diff_nonzero = (merged["delta_call"] != 0).sum()
    print(f"  Pairs with put strike diff ≠ 0:  {put_diff_nonzero} ({put_diff_nonzero/n_matched*100:.1f}%)")
    print(f"  Pairs with call strike diff ≠ 0: {call_diff_nonzero} ({call_diff_nonzero/n_matched*100:.1f}%)")

    # Merge P&L for trades that diverged materially
    merged_pnl = pd.merge(
        df_old[["entry_date", "pnl"]].rename(columns={"pnl": "pnl_old"}),
        df_new[["entry_date", "pnl"]].rename(columns={"pnl": "pnl_new"}),
        on="entry_date",
        how="inner",
    )
    merged_pnl["abs_delta"] = (merged_pnl["pnl_new"] - merged_pnl["pnl_old"]).abs()
    big = merged_pnl[merged_pnl["abs_delta"] > 50].sort_values("abs_delta", ascending=False)
    if len(big) > 0:
        print(f"\n  Trades with |Δ P&L| > R$50: {len(big)}")
        for _, row in big.head(10).iterrows():
            print(
                f"    {row['entry_date'].date()}  "
                f"old={row['pnl_old']:+.0f}  "
                f"new={row['pnl_new']:+.0f}  "
                f"Δ={row['pnl_new'] - row['pnl_old']:+.0f}"
            )

    return merged


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    results = {}
    for market in ("bova11", "petr4"):
        print(f"\n{'─'*60}")
        print(f"  Running {market.upper()}")
        print(f"{'─'*60}")

        df_old = run_one(market, OLD_DB, "old")
        df_new = run_one(market, NEW_DB, "rb3")
        merged = compare(market, df_old, df_new)
        results[market] = {"old": df_old, "new": df_new, "merged": merged}

    return results


if __name__ == "__main__":
    main()
