"""Phase 4: Full PETR4 grid search (same spec as BOVA11 v7).

Runs only if pilot (phase4_petr4_pilot.py) showed mid holdout median > 0.
Saves to data/B3/v7_petr4_grid_search_results.parquet.
"""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import time
from pathlib import Path
from grid_search import run_grid, enumerate_grid

OUT_PATH = Path("data/B3/v7_petr4_grid_search_results.parquet")

GRID = {
    "target_delta": [0.12, 0.16, 0.20, 0.25],
    "dte_max": [21, 30, 45, 60],
    "profit_target_pct": [0.25, 0.50],
    "manage_at_dte": [5, 7, 14, 21],
    "vix_filter": ["OFF", "rv_pct:70", "rv_pct:80", "rv_pct:90"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [2.0, 3.0],
    "execution_mode": ["bid_ask", "mid", "mid_plus_1tick"],
    "portfolio_mode": ["laddering"],
}

RUNS = [
    ("train",   "petr4", "2018-01-02", "2022-12-30"),
    ("holdout", "petr4", "2023-01-02", "2025-11-30"),
]

combos = enumerate_grid(GRID)
print(f"PETR4 Grid: {len(combos)} valid combos × 2 periods = {len(combos) * 2} backtests")

start = time.time()
df = run_grid(GRID, RUNS, output_path=OUT_PATH)
elapsed = time.time() - start

print(f"\nCompleted in {elapsed/60:.1f} minutes")
print(f"Results: {len(df)} rows saved to {OUT_PATH}")

# Quick summary
import pandas as pd
valid = df[df["error"].isna() & (df["n_trades"] >= 30)]
holdout = valid[valid["period_label"] == "holdout"]
print(f"\nValid rows: {len(valid)}")
print("\nHoldout median Sharpe by execution_mode:")
for mode in ["bid_ask", "mid", "mid_plus_1tick"]:
    sub = holdout[holdout["execution_mode"] == mode]["sharpe"]
    print(f"  {mode:16s} median={sub.median():.3f}  pct_positive={( sub>0).mean():.1%}  n={len(sub)}")
