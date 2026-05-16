#!/usr/bin/env python3
"""Reprocess v7 parquet files with corrected Sharpe and new info_ratio.

After the risk-free rate fix in metrics.py (commits ca08d04, 9be6d6f, 7907a42),
the sharpe column in the v7 parquet uses the old no-rf-subtraction formula
and there is no info_ratio column. This script:

1. Loads v7_grid_search_results.parquet and v7_petr4_grid_search_results.parquet
2. For each row, re-runs the backtest with identical config/engine/data
3. Uses the fixed compute_portfolio_metrics to get corrected sharpe + info_ratio
4. Overwrites the parquet files

Matches the original grid_search.py approach:
  - mode="market" (MarketEngine with SQLite DB)
  - Engine cached by (target_delta, market), _exec_mode toggled per row
  - Data cached by (market, start_date, end_date)

Runtime: ~2.5 hours for 10,752 backtests.

Usage:
    python scripts/reprocess_v7_sharpes.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import Tuple

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from straddle import run_portfolio_backtest  # noqa: E402
from straddle.metrics import compute_portfolio_metrics  # noqa: E402
from straddle.data import load_market_data  # noqa: E402
from straddle.engines import make_engine  # noqa: E402
from straddle.params import PARAMS, apply_market_preset  # noqa: E402


# ── Engine cache (matches grid_search.py _worker_cache pattern) ────────────────

_engine_cache: Dict[Tuple[str, str, str], Tuple[pd.DataFrame, object]] = {}


def _get_data_and_engine(
    market: str, start_date: str, end_date: str, target_delta: float,
    execution_mode: str,
) -> Tuple[pd.DataFrame, object]:
    """Get or create (data, engine) for this (market, start, end) period.

    Engine is created once per period with the first combo's params, then
    _exec_mode and uses_real_fills are toggled per row (same pattern as
    grid_search.py:205-214). The PricingContext supplies target_delta per
    backtest independent of the cached engine.
    """
    cache_key = (market, str(start_date), str(end_date))
    if cache_key not in _engine_cache:
        params = dict(PARAMS)
        params = apply_market_preset(params, market)
        params["mode"] = "market"
        params["target_delta"] = target_delta
        params["cash_investment_mode"] = "risk_free"
        params["cash_yield_annual"] = 0.0
        data = load_market_data(start_date, end_date, market=market)
        engine = make_engine(params)
        _engine_cache[cache_key] = (data, engine)
    data, engine = _engine_cache[cache_key]
    # Toggle execution mode (engine is shared across all combos in this period)
    engine._exec_mode = execution_mode
    engine.uses_real_fills = (execution_mode == "bid_ask")
    return data, engine


def _close_engines() -> None:
    for _, engine in _engine_cache.values():
        if hasattr(engine, "close"):
            engine.close()
    _engine_cache.clear()


# ── Param reconstruction ──────────────────────────────────────────────────────

def _build_params(row: pd.Series, market: str) -> dict:
    """Reconstruct the params dict matching grid_search.py _apply_grid_overrides."""
    vix_filter = row.get("vix_filter", "OFF")
    if isinstance(vix_filter, str) and vix_filter.startswith("rv_pct:"):
        overrides = dict(
            vol_filter_mode="rv_pct",
            vol_filter_threshold=float(vix_filter.split(":")[1]),
        )
    elif isinstance(vix_filter, str) and vix_filter.startswith("ivr:"):
        overrides = dict(
            vol_filter_mode="ivr",
            vol_filter_threshold=float(vix_filter.split(":")[1]),
        )
    else:  # OFF
        overrides = dict(
            vol_filter_mode="off",
            vol_filter_threshold=0.0,
            vix_entry_filter_enabled=False,
            vix_entry_max=999.0,
        )

    dte_max = int(row["dte_max"])
    portfolio_mode = str(row.get("portfolio_mode", "laddering"))
    # Match _apply_grid_overrides (grid_search.py:60-81)
    overrides.update(
        target_delta=float(row["target_delta"]),
        dte_max=dte_max,
        dte_min={21: 15, 30: 20, 45: 30, 60: 45}[dte_max],
        profit_target_pct=float(row["profit_target_pct"]),
        stop_loss_pct=float(row["stop_loss_pct"]),
        use_price_stop=True,
        manage_at_dte=int(row["manage_at_dte"]),
        execution_mode=str(row["execution_mode"]),
        portfolio_mode=portfolio_mode,
        single_position=(portfolio_mode != "laddering"),
        roll_for_credit=True,
        max_rolls=3,
        commission_per_leg=1.0,
        initial_balance=25000.0,
        cash_investment_mode="risk_free",
        cash_yield_annual=0.0,
        underlying_allocation_pct=0.0,
        max_bpr_allocation=0.30,
        defensive_leg_roll_enabled=False,
    )

    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params["mode"] = "market"
    params["cash_investment_mode"] = "risk_free"
    params["cash_yield_annual"] = 0.0
    params["start_date"] = str(row["start_date"])
    params["end_date"] = str(row["end_date"])
    params.update(overrides)
    return params


def _run_one(row: pd.Series, market: str) -> Tuple[float, float]:
    """Run backtest for one parquet row. Returns (sharpe, info_ratio)."""
    try:
        params = _build_params(row, market)
        data, engine = _get_data_and_engine(
            market, str(row["start_date"]), str(row["end_date"]),
            params["target_delta"], params["execution_mode"],
        )
        trades, equity_df, _, _ = run_portfolio_backtest(
            data, params, engine, progress=False,
        )
        metrics = compute_portfolio_metrics(trades, equity_df, params, data)
        sharpe = float(metrics.get("sharpe", 0.0))
        info_ratio = float(metrics.get("info_ratio", sharpe))
        return sharpe, info_ratio
    except Exception as e:
        tqdm.write(f"  ERROR row {row.name}: {e}")
        return None, None


def _reprocess_parquet(parquet_path: Path, market: str) -> pd.DataFrame:
    """Reprocess a single parquet file, returning updated DataFrame."""
    tqdm.write(f"\nLoading {parquet_path} ...")
    df = pd.read_parquet(parquet_path)

    if "info_ratio" not in df.columns:
        df["info_ratio"] = 0.0

    total = len(df)
    tqdm.write(f"  {total} rows ({market})")

    for idx in tqdm(range(total), desc=f"Reprocessing {market}", unit="row"):
        row = df.iloc[idx]
        if isinstance(row.get("error"), str) and row["error"]:
            continue
        sharpe, info_ratio = _run_one(row, market)
        if sharpe is not None:
            df.at[idx, "sharpe"] = sharpe
            df.at[idx, "info_ratio"] = info_ratio
            # Leave all other columns unchanged — the total_return, max_drawdown,
            # win_rate, etc. from the original v7 run are the canonical values.
            # Only sharpe and info_ratio are recomputed via the fixed metrics code.

    return df


def main():
    start_time = time.time()

    files = [
        (ROOT / "data" / "B3" / "v7_grid_search_results.parquet", "bova11"),
        (ROOT / "data" / "B3" / "v7_petr4_grid_search_results.parquet", "petr4"),
    ]

    for parquet_path, market in files:
        if not parquet_path.exists():
            print(f"SKIP: {parquet_path} not found")
            continue

        backup_path = parquet_path.with_suffix(".parquet.bak")
        if not backup_path.exists():
            tqdm.write(f"  Backing up to {backup_path.name} ...")
            shutil.copy2(parquet_path, backup_path)

        df_updated = _reprocess_parquet(parquet_path, market)

        # ── Comparison summary ────────────────────────────────────────────
        df_orig = pd.read_parquet(backup_path)

        tqdm.write(f"\n{'='*60}")
        tqdm.write(f"Summary: {parquet_path.name}")
        tqdm.write(f"{'='*60}")
        for period in sorted(df_updated["period_label"].unique()):
            sub_new = df_updated[
                (df_updated["period_label"] == period) & df_updated["error"].isna()
            ]
            sub_old = df_orig[
                (df_orig["period_label"] == period) & df_orig["error"].isna()
            ]
            if len(sub_new) == 0:
                continue
            tqdm.write(f"\n  {period}:")
            tqdm.write(f"    Rows reprocessed: {len(sub_new)}")
            tqdm.write(f"    Old sharpe median: {sub_old['sharpe'].median():.4f}")
            tqdm.write(f"    New sharpe median: {sub_new['sharpe'].median():.4f}")
            tqdm.write(f"    Δ sharpe median:   {sub_new['sharpe'].median() - sub_old['sharpe'].median():+.4f}")
            tqdm.write(f"    Info ratio median: {sub_new['info_ratio'].median():.4f}")

            for mode in ["bid_ask", "mid", "mid_plus_1tick"]:
                sm_new = sub_new[sub_new["execution_mode"] == mode]
                sm_old = sub_old[sub_old["execution_mode"] == mode]
                if len(sm_new) == 0:
                    continue
                delta = sm_new["sharpe"].median() - sm_old["sharpe"].median()
                tqdm.write(
                    f"      {mode:<18} old={sm_old['sharpe'].median():.4f}  "
                    f"new={sm_new['sharpe'].median():.4f}  "
                    f"Δ={delta:+.4f}  info={sm_new['info_ratio'].median():.4f}"
                )

        tqdm.write(f"\n  Writing updated parquet ...")
        df_updated.to_parquet(parquet_path, index=False)
        tqdm.write(f"  Done. Wrote {len(df_updated)} rows.\n")

    _close_engines()

    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed / 60:.1f} min ({elapsed / 3600:.2f} h)")


if __name__ == "__main__":
    main()
