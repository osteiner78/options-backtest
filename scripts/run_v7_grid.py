"""Run v7 refined grid search for BOVA11.

v7 refines v6 by:
- Dropping 30Δ and 50Δ/straddle (consistently poor performers)
- Dropping 0.75 profit target (little differentiation)
- Dropping defensive_leg_roll (ΔSharpe ±0.03, negligible)
- Keeping all DTE and vol-filter levels for interaction analysis

Usage: python scripts/run_v7_grid.py [--n-workers N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

V7_GRID = {
    "target_delta":      [0.12, 0.16, 0.20, 0.25],
    "dte_max":           [21, 30, 45, 60],
    "profit_target_pct": [0.25, 0.50],
    "manage_at_dte":     [5, 7, 14, 21],
    "vix_filter":        ["OFF", "rv_pct:70", "rv_pct:80", "rv_pct:90"],
    "defensive_leg_roll":[False],
    "stop_loss_pct":     [2.0, 3.0],
    "execution_mode":    ["bid_ask", "mid", "mid_plus_1tick"],
    "portfolio_mode":    ["laddering"],
}
# 4×4×2×4×4×1×2×3×1 = 3,072 raw; ~2,300 valid after manage_at_dte < dte_min filter

V7_RUNS = [
    ("train",   "bova11", "2018-01-02", "2022-12-30"),
    ("holdout", "bova11", "2023-01-02", "2025-11-30"),
]

OUTPUT_PATH = Path("data/B3/v7_grid_search_results.parquet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v7 BOVA11 grid search")
    parser.add_argument("--n-workers", type=int, default=-1,
                        help="Parallel workers (-1 = all CPUs, default)")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from grid_search import run_grid, enumerate_grid

    print("=== v7 BOVA11 Grid Search ===")
    print(f"Output: {OUTPUT_PATH}")
    combos = enumerate_grid(V7_GRID)
    print(f"Valid combos: {len(combos)}  ×  {len(V7_RUNS)} periods = {len(combos) * len(V7_RUNS)} total runs")

    df = run_grid(V7_GRID, V7_RUNS, n_workers=args.n_workers, output_path=OUTPUT_PATH)

    print(f"\nDone! {len(df)} rows saved to {OUTPUT_PATH}")
    n_err = int(df["error"].notna().sum())
    if n_err == 0:
        print("No errors.")
    else:
        print(f"{n_err} errors — check 'error' column in parquet.")
    print(f"Sharpe range (holdout, mid_plus_1tick): "
          f"{df[(df['period_label']=='holdout') & (df['execution_mode']=='mid_plus_1tick')]['sharpe'].describe()[['min','max','mean']].to_dict()}")


if __name__ == "__main__":
    main()
