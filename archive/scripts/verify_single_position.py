#!/usr/bin/env python3
"""A.1 — Re-run v5 grid with fixed engine cache (Option B: both modes).

Laddering run (192 backtests): cache-bug test vs v5_grid_search_results.parquet.
Single_position run (192 backtests): new baseline for future comparisons.

Decision gate: max |new_laddering_median - old_median| per execution_mode < 0.10.
  PASS → cache bug had no material impact on original v5 results.
  FAIL → original was corrupted; use fixed results as authoritative.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

GRID_V5 = {
    "target_delta": [0.16, 0.20, 0.25],
    "dte_max": [30, 45],
    "profit_target_pct": [0.50],
    "manage_at_dte": [7, 14],
    "vix_filter": ["OFF", "rv_pct:80"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [3.0],
    "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"],
}

RUNS = [
    ("train",   "bova11", "2018-01-02", "2022-12-31"),
    ("holdout", "bova11", "2023-01-02", "2025-11-30"),
]

OUT_DIR = ROOT / "data" / "B3"
ORIGINAL_PATH   = OUT_DIR / "v5_grid_search_results.parquet"
LADDERING_PATH  = OUT_DIR / "v5_grid_search_laddering_fixed.parquet"
SINGLEPOS_PATH  = OUT_DIR / "v5_grid_search_singlepos_fixed.parquet"


def _run_mode(portfolio_mode: str, out_path: Path) -> pd.DataFrame:
    from grid_search import run_grid, enumerate_grid

    if out_path.exists():
        print(f"Loading cached {portfolio_mode} results from {out_path}")
        return pd.read_parquet(out_path)

    grid = {**GRID_V5, "portfolio_mode": [portfolio_mode]}
    combos = enumerate_grid(grid)
    print(f"\n--- Running {portfolio_mode}: {len(combos)} combos × {len(RUNS)} periods "
          f"= {len(combos) * len(RUNS)} backtests ---")
    return run_grid(grid, RUNS, output_path=out_path)


def _compare(original: pd.DataFrame, fixed: pd.DataFrame, period: str) -> tuple[bool, str]:
    """Compare median Sharpe per execution_mode between original and fixed laddering.

    Returns (pass, detail_text).
    """
    modes = ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"]
    orig_p  = original[original["period_label"] == period]
    fixed_p = fixed[(fixed["period_label"] == period) & (fixed["error"].isna())]

    lines = [f"  {'execution_mode':<22} {'orig_median':>12} {'fixed_median':>13} {'diff':>8}"]
    lines.append("  " + "-" * 60)
    max_diff = 0.0
    for mode in modes:
        orig_med  = orig_p[orig_p["execution_mode"] == mode]["sharpe"].median()
        fixed_med = fixed_p[fixed_p["execution_mode"] == mode]["sharpe"].median()
        diff = fixed_med - orig_med
        max_diff = max(max_diff, abs(diff))
        lines.append(f"  {mode:<22} {orig_med:>12.4f} {fixed_med:>13.4f} {diff:>+8.4f}")

    passed = max_diff < 0.10
    verdict = "PASS" if passed else "FAIL"
    lines.append(f"\n  max |diff| = {max_diff:.4f} → {verdict} (threshold 0.10)")
    return passed, "\n".join(lines)


def main() -> None:
    # Run (or load) both modes
    df_laddering  = _run_mode("laddering",       LADDERING_PATH)
    df_singlepos  = _run_mode("single_position", SINGLEPOS_PATH)

    # Load original v5 results
    if not ORIGINAL_PATH.exists():
        print(f"ERROR: {ORIGINAL_PATH} not found — cannot compare.")
        return

    df_orig = pd.read_parquet(ORIGINAL_PATH)
    df_orig_valid = df_orig[df_orig["error"].isna()].copy()

    print("\n" + "=" * 65)
    print("A.1 — Cache Bug Test: laddering (fixed) vs v5_grid_search_results")
    print("=" * 65)

    for period in ["train", "holdout"]:
        print(f"\n  Period: {period}")
        passed, detail = _compare(df_orig_valid, df_laddering, period)
        print(detail)

    print("\n" + "=" * 65)
    print("A.1 — Single_position baseline summary (new, fixed cache)")
    print("=" * 65)
    modes = ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"]
    df_sp_valid = df_singlepos[df_singlepos["error"].isna()]
    for period in ["train", "holdout"]:
        print(f"\n  Period: {period}")
        for mode in modes:
            sub = df_sp_valid[
                (df_sp_valid["period_label"] == period) &
                (df_sp_valid["execution_mode"] == mode)
            ]
            print(f"    {mode:<22} n={len(sub):3d}  "
                  f"median_sharpe={sub['sharpe'].median():+.4f}")

    # Error summary
    for label, df in [("laddering_fixed", df_laddering), ("singlepos_fixed", df_singlepos)]:
        n_err = int(df["error"].notna().sum())
        if n_err:
            print(f"\nWARNING: {n_err} errors in {label}")


if __name__ == "__main__":
    main()
