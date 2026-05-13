"""Step 2: Quantify synthetic fallback dominance.

Runs a single BOVA11 backtest with the v2 top config and reports P&L broken
down by entry_source (db vs synthetic).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import numpy as np
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset

ROOT = Path(__file__).resolve().parent.parent

# v2 top BOVA11 config: d=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF
CONFIG = {
    "target_delta": 0.30,
    "dte_min": 30,
    "dte_max": 45,
    "manage_at_dte": 14,
    "profit_target_pct": 0.75,
    "vol_filter_mode": "off",
    "defensive_leg_roll_enabled": False,
    "single_position": True,
    "mode": "market",
}


def main():
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    params.update(CONFIG)
    params["start_date"] = "2020-04-01"
    params["end_date"] = "2025-12-31"

    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market="bova11",
    )

    engine = make_engine(params)
    try:
        trades, equity, skipped, vix_blocked = run_backtest(data, params, engine)
    finally:
        engine.close()

    # Build dataframe with source info
    rows = []
    for t in trades:
        rows.append({
            "trade_num": t.trade_num,
            "entry_date": t.entry_date,
            "entry_source": getattr(t, "entry_source", "unknown"),
            "exit_source": getattr(t, "exit_source", "unknown"),
            "mtm_db_pct": getattr(t, "mtm_source_days", 0) / max(getattr(t, "mtm_total_days", 1), 1),
            "pnl": t.pnl,
            "exit_type": t.exit_type,
            "roll_count": t.roll_count,
        })
    df = pd.DataFrame(rows)

    print("\n" + "=" * 60)
    print("  BOVA11 Synthetic vs Real DB Breakdown")
    print("  Config: d=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF")
    print("=" * 60)

    # Entry source breakdown
    db_trades = df[df["entry_source"] == "db"]
    synth_trades = df[df["entry_source"] == "synthetic"]
    total = len(df)

    print(f"\n  Total trades: {total}")
    print(f"  DB entries: {len(db_trades)} ({len(db_trades)/total*100:.1f}%)")
    print(f"  Synthetic entries: {len(synth_trades)} ({len(synth_trades)/total*100:.1f}%)")

    # P&L by source
    if len(db_trades) > 0:
        pnl_db = db_trades["pnl"].dropna()
        print(f"\n  DB-entry P&L:")
        print(f"    Total:   R${pnl_db.sum():+,.2f}")
        print(f"    Mean:    R${pnl_db.mean():+,.2f}")
        print(f"    Win rate: {(pnl_db > 0).mean()*100:.1f}%")
        print(f"    N:        {len(pnl_db)}")

    if len(synth_trades) > 0:
        pnl_synth = synth_trades["pnl"].dropna()
        print(f"\n  Synthetic-entry P&L:")
        print(f"    Total:   R${pnl_synth.sum():+,.2f}")
        print(f"    Mean:    R${pnl_synth.mean():+,.2f}")
        print(f"    Win rate: {(pnl_synth > 0).mean()*100:.1f}%")
        print(f"    N:        {len(pnl_synth)}")

    # Chains: how many root chains start with synthetic entry?
    roots = df[df["roll_count"] == 0]
    db_roots = roots[roots["entry_source"] == "db"]
    synth_roots = roots[roots["entry_source"] == "synthetic"]
    print(f"\n  Root chains:")
    print(f"    DB entry:         {len(db_roots)} ({len(db_roots)/len(roots)*100:.1f}%)")
    print(f"    Synthetic entry:  {len(synth_roots)} ({len(synth_roots)/len(roots)*100:.1f}%)")

    # MTM source breakdown
    avg_db_pct = df["mtm_db_pct"].mean()
    median_db_pct = df["mtm_db_pct"].median()
    print(f"\n  MTM source (average % of days using DB data):")
    print(f"    Mean:   {avg_db_pct*100:.1f}%")
    print(f"    Median: {median_db_pct*100:.1f}%")

    # Mixed chains: entry=DB but MTM mostly synthetic
    mixed = df[(df["entry_source"] == "db") & (df["mtm_db_pct"] < 0.5)]
    print(f"\n  Mixed chains (DB entry, <50% DB MTM): {len(mixed)}")

    # Save detailed output
    out_dir = ROOT / "output" / "synthetic_diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "bova11_source_breakdown.parquet")
    print(f"\n  Saved to {out_dir / 'bova11_source_breakdown.parquet'}")


if __name__ == "__main__":
    main()
