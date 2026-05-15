"""Spot-check 3 random configs: compare parquet (old) vs standalone (new) Sharpe."""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grid_search import _run_one

CHECKS = [
    # (desc, old_sharpe, market, period, start, end, combo)
    (
        "25Δ/dte21/pt50%/rv90/stop3/mid holdout",
        0.775488,
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
         "manage_at_dte": 7, "vix_filter": "rv_pct:90", "stop_loss_pct": 3.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "16Δ/dte60/pt50%/OFF/stop2/mid holdout",
        0.279056,
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        {"target_delta": 0.16, "dte_max": 60, "profit_target_pct": 0.50,
         "manage_at_dte": 21, "vix_filter": "OFF", "stop_loss_pct": 2.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
    (
        "20Δ/dte30/pt50%/rv80/stop3/mid holdout",
        -0.495996,
        "bova11", "holdout", "2023-01-02", "2025-11-30",
        {"target_delta": 0.20, "dte_max": 30, "profit_target_pct": 0.50,
         "manage_at_dte": 5, "vix_filter": "rv_pct:80", "stop_loss_pct": 3.0,
         "execution_mode": "mid", "portfolio_mode": "laddering",
         "defensive_leg_roll": False},
    ),
]


def main() -> None:
    print("=== Phase 5 Spot-Check: 3 Random Configs ===\n")
    print(f"{'Config':<45} {'Old Sharpe':>10} {'New Sharpe':>10} {'Δ':>7}")
    print("-" * 80)
    all_pass = True
    for desc, old_sharpe, market, period, start, end, combo in CHECKS:
        result = _run_one(market, period, start, end, combo)
        if result.get("error"):
            print(f"ERROR: {result['error']}")
            all_pass = False
            continue
        new_sharpe = result["sharpe"]
        delta = new_sharpe - old_sharpe
        flag = "" if abs(delta) < 0.15 else " *** LARGE DELTA ***"
        print(f"{desc:<45} {old_sharpe:>10.3f} {new_sharpe:>10.3f} {delta:>+7.3f}{flag}")
        if abs(delta) >= 0.15:
            all_pass = False

    print()
    if all_pass:
        print("PASS — all spot-checks within 0.15 Δ threshold.")
    else:
        print("FAIL — at least one spot-check exceeds 0.15 threshold.")


if __name__ == "__main__":
    main()
