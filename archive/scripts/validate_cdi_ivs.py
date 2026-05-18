"""Step 4.6: Validate CDI IVs produce stable strike selection.

Re-runs the Phase 1 regression with use_cdi_ivs=True and compares
strike selection trade-by-trade against the flat-12% results.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset

ROOT = Path(__file__).resolve().parent.parent
START = "2017-01-02"
END = "2025-12-31"


def run_one(market: str, use_cdi: bool, label: str) -> pd.DataFrame:
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params["start_date"] = START
    params["end_date"] = END
    params["mode"] = "market"
    params["vix_entry_max"] = 35.0 if market == "bova11" else 80.0
    params["use_cdi_ivs"] = use_cdi

    data = load_market_data(start_date=START, end_date=END, market=market)
    engine = make_engine(params)
    try:
        trades, _, _, _ = run_backtest(data, params, engine)
    finally:
        engine.close()

    rows = []
    for t in trades:
        rows.append({
            "entry_date": t.entry_date,
            "put_strike": t.put_strike,
            "call_strike": t.call_strike,
            "net_credit": t.net_credit,
            "pnl": t.pnl,
            "entry_source": getattr(t, "entry_source", "unknown"),
        })
    df = pd.DataFrame(rows)
    print(f"  [{label}] {len(df)} trades, P&L={df['pnl'].sum():+,.2f}")
    return df


def compare(market: str, df_flat: pd.DataFrame, df_cdi: pd.DataFrame):
    merged = pd.merge(
        df_flat[["entry_date", "put_strike", "call_strike", "net_credit", "pnl"]].rename(
            columns={"put_strike": "put_flat", "call_strike": "call_flat",
                     "net_credit": "credit_flat", "pnl": "pnl_flat"}),
        df_cdi[["entry_date", "put_strike", "call_strike", "net_credit", "pnl"]].rename(
            columns={"put_strike": "put_cdi", "call_strike": "call_cdi",
                     "net_credit": "credit_cdi", "pnl": "pnl_cdi"}),
        on="entry_date", how="inner",
    )

    n = len(merged)
    put_same = (merged["put_flat"] == merged["put_cdi"]).sum()
    call_same = (merged["call_flat"] == merged["call_cdi"]).sum()

    print(f"\n  {market.upper()} - flat-12% vs CDI strike selection:")
    print(f"    Matched trades:             {n}")
    print(f"    Same put strike:            {put_same}/{n} ({put_same/n*100:.1f}%)")
    print(f"    Same call strike:           {call_same}/{n} ({call_same/n*100:.1f}%)")
    print(f"    Both strikes same:          {(merged['put_flat'] == merged['put_cdi']).sum()}/{n}")
    print(f"    Mean put strike diff:        {(merged['put_cdi'] - merged['put_flat']).mean():+.2f}")
    print(f"    Mean call strike diff:       {(merged['call_cdi'] - merged['call_flat']).mean():+.2f}")
    print(f"    P&L delta:                  R${merged['pnl_cdi'].sum() - merged['pnl_flat'].sum():+,.2f}")

    if put_same / n >= 0.95 and call_same / n >= 0.95:
        print(f"    DECISION: Stable (>95% same strikes) - adopt CDI as default")
    else:
        print(f"    DECISION: Unstable (<95% same strikes) - investigate before adopting")
    return merged


def main():
    for market in ("bova11", "petr4"):
        print(f"\n{'-'*60}")
        print(f"  {market.upper()}")
        print(f"{'-'*60}")
        df_flat = run_one(market, use_cdi=False, label=f"{market}_flat")
        df_cdi = run_one(market, use_cdi=True, label=f"{market}_cdi")
        compare(market, df_flat, df_cdi)


if __name__ == "__main__":
    main()
