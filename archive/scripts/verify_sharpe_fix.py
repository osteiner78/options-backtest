"""Step 3: Verify the daily MTM Sharpe fix produces sane values.

Re-runs the worst PETR4 configuration from the v2 grid search
(target_delta=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF)
and reports both old-style (P&L-smearing proxy) and new-style Sharpe.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset
from straddle.metrics import compute_metrics

ROOT = Path(__file__).resolve().parent.parent


def run_and_report(market: str, config: dict, label: str):
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params.update(config)
    params["start_date"] = "2020-04-01"
    params["end_date"] = "2025-12-31"

    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market=market,
    )

    engine = make_engine(params)
    try:
        trades, equity, skipped, vix_blocked = run_backtest(data, params, engine)
    finally:
        engine.close()

    metrics = compute_metrics(trades, equity, params, data)

    print(f"\n  {label}:")
    print(f"    Trades:       {metrics.get('n', 0)}")
    print(f"    Total P&L:    R${sum(t.pnl for t in trades if t.pnl is not None):+,.2f}")
    print(f"    Win rate:      {metrics.get('wr', 0)*100:.1f}%")
    print(f"    Sharpe:        {metrics.get('sharpe', 'N/A')}")
    print(f"    MDD:           {metrics.get('mdd', 0)*100:.1f}%")
    print(f"    Calmar:        {metrics.get('calmar', 'N/A')}")

    # Verify daily_marks exist and sum correctly
    for t in trades[:3]:
        marks = t.daily_marks
        if marks and len(marks) >= 2:
            daily_deltas = [marks[i][1] - marks[i-1][1] for i in range(1, len(marks))]
            mark_sum = sum(daily_deltas)
            pnl_direct = t.pnl or 0.0
            diff = abs(mark_sum - pnl_direct)
            if diff > 1.0:
                print(f"    WARNING: Trade {t.trade_num} daily_marks sum={mark_sum:.2f}, pnl={pnl_direct:.2f}, diff={diff:.2f}")

    return trades, metrics


def main():
    print("=" * 60)
    print("  Sharpe Verification")
    print("  Testing whether daily MTM Sharpe produces sane values")
    print("=" * 60)

    # v2 configs that showed extreme Sharpe
    configs = {
        "PETR4 worst (d=0.30)": {
            "target_delta": 0.30,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 14,
            "profit_target_pct": 0.75,
            "vol_filter_mode": "off",
            "defensive_leg_roll_enabled": False,
            "mode": "market",
        },
        "BOVA11 best (d=0.30)": {
            "target_delta": 0.30,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 14,
            "profit_target_pct": 0.75,
            "vol_filter_mode": "off",
            "defensive_leg_roll_enabled": False,
            "mode": "market",
        },
        "PETR4 baseline (d=0.16)": {
            "target_delta": 0.16,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 21,
            "profit_target_pct": 0.50,
            "vol_filter_mode": "vix",
            "vix_entry_max": 80.0,
            "mode": "market",
        },
        "BOVA11 baseline (d=0.16)": {
            "target_delta": 0.16,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 21,
            "profit_target_pct": 0.50,
            "vol_filter_mode": "vix",
            "vix_entry_max": 50.0,
            "mode": "market",
        },
    }

    results = {}
    all_trades = {}
    for label, config in configs.items():
        market = "petr4" if "PETR4" in label else "bova11"
        trades, metrics = run_and_report(market, config, label)
        results[label] = metrics
        all_trades[label] = trades

    print("\n" + "=" * 60)
    print("  VERIFICATION SUMMARY")
    print("=" * 60)
    print("  Expected: Sharpe values in [-2, +2] range")
    print("  If Sharpe still > |5|, the fix is incomplete.")
    print()
    for label, m in results.items():
        sharpe = m.get("sharpe", "N/A")
        if isinstance(sharpe, float):
            sane = "SANE" if abs(sharpe) < 5 else "EXTREME"
        else:
            sane = "UNKNOWN"
        print(f"  {label}: Sharpe={sharpe:.2f} {sane}" if isinstance(sharpe, float) else f"  {label}: Sharpe={sharpe} {sane}")

    # Manual verification: pick the longest-holding trade from the worst config
    worst_label = "PETR4 worst (d=0.30)"
    trades = all_trades.get(worst_label, [])
    if trades:
        longest = max(trades, key=lambda t: len(t.daily_marks) if t.daily_marks else 0)
        print(f"\n  Manual verification - Trade {longest.trade_num} ({worst_label}):")
        print(f"    Entry: {longest.entry_date.date()}, Exit: {longest.exit_date.date()}")
        print(f"    P&L (realized): R${longest.pnl:+.2f}")
        if longest.daily_marks and len(longest.daily_marks) > 1:
            deltas = [longest.daily_marks[i][1] - longest.daily_marks[i-1][1]
                       for i in range(1, len(longest.daily_marks))]
            print(f"    P&L (sum of daily deltas): R${sum(deltas):+.2f}")
            print(f"    # of daily marks: {len(longest.daily_marks)}")
            non_zero_days = sum(1 for d in deltas if abs(d) > 0.01)
            print(f"    Non-zero daily deltas: {non_zero_days}/{len(deltas)}")


if __name__ == "__main__":
    main()
