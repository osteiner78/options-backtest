"""Measure I-10 Sharpe fix impact on key configs.

Runs 5 standalone backtests with the current (fixed) code and compares against
old Sharpe values recorded in the v7 parquets (generated before the I-10 fix).

Usage: python scripts/measure_sharpe_impact.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grid_search import _run_one

CONFIGS = [
    # (label, market, period_label, start_date, end_date, old_sharpe, combo)
    (
        "25Δ BOVA11",
        "bova11", "train", "2018-01-02", "2022-12-30",
        0.908194,
        {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "25Δ BOVA11",
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        1.292191,
        {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "16Δ BOVA11",
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        1.883262,
        {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 14, "vix_filter": "rv_pct:70", "stop_loss_pct": 3.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "12Δ BOVA11",
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        11.557057,
        {"target_delta": 0.12, "dte_max": 30, "profit_target_pct": 0.25,
         "manage_at_dte": 7, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0,
         "execution_mode": "mid_plus_1tick", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "25Δ PETR4",
        "petr4", "train", "2018-01-02", "2022-12-30",
        0.613049,
        {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "25Δ PETR4",
        "petr4", "holdout", "2023-01-02", "2025-11-30",
        1.211361,
        {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
]


def main() -> None:
    print("=== I-10 Sharpe Impact Measurement ===\n")
    print(f"{'Config':<14} {'Period':<8} {'Old Sharpe':>10} {'New Sharpe':>10} {'Δ':>7} {'Old Return':>10} {'n_trades':>8}")
    print("-" * 80)

    max_delta = 0.0
    rows = []

    for label, market, period, start, end, old_sharpe, combo in CONFIGS:
        print(f"  Running {label} {period} ({start}–{end})...", flush=True)
        result = _run_one(market, period, start, end, combo)
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
            continue
        new_sharpe = result["sharpe"]
        delta = new_sharpe - old_sharpe
        total_return = result["total_return"]
        n_trades = result["n_trades"]
        rows.append((label, period, old_sharpe, new_sharpe, delta, total_return, n_trades))
        max_delta = max(max_delta, abs(delta))

    print()
    print(f"{'Config':<14} {'Period':<8} {'Old Sharpe':>10} {'New Sharpe':>10} {'Δ':>7} {'Old Return':>10} {'n_trades':>8}")
    print("-" * 80)
    for label, period, old_s, new_s, delta, ret, n in rows:
        print(f"{label:<14} {period:<8} {old_s:>10.3f} {new_s:>10.3f} {delta:>+7.3f} {ret:>10.1%} {n:>8}")

    print()
    print(f"Max |ΔSharpe| across all configs: {max_delta:.3f}")
    print()
    if max_delta < 0.15:
        print("DECISION: ΔSharpe < 0.15 — fix is immaterial, do NOT re-run full grid.")
        print("Action: Update report §§1,5,9,10 with a note on corrected numbers.")
    else:
        print(f"DECISION: ΔSharpe >= 0.15 — RE-RUN full grid (Phase 3 triggered).")


if __name__ == "__main__":
    main()
