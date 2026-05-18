#!/usr/bin/env python3
"""Entry cooldown sensitivity grid for BOVA11 recommended config.

Fixed base: 25Δ/pt50%/manage14/OFF/stop2.0/mid/laddering
Sensitivity: entry_cooldown_days × dte_max × period
"""
import sys
from itertools import product
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from straddle import (
    PARAMS, load_market_data, make_engine,
    run_portfolio_backtest, compute_portfolio_metrics,
)
from straddle.params import apply_market_preset

COOLDOWNS          = [1, 2, 3, 5, 7]
DTE_MAXES          = [21, 30, 45]
DTE_MIN_BY_DTE_MAX = {21: 15, 30: 20, 45: 30}

PERIODS = [
    ("train",   "2018-01-02", "2022-12-30"),
    ("holdout", "2023-01-02", "2025-11-30"),
]

BASE = {
    "target_delta":             0.25,
    "profit_target_pct":        0.50,
    "manage_at_dte":            14,
    "vix_entry_filter_enabled": False,
    "stop_loss_pct":            2.0,
    "execution_mode":           "mid",
    "portfolio_mode":           "laddering",
    "mode":                     "market",
}

rows = []
for (period_label, start, end), cooldown, dte_max in product(PERIODS, COOLDOWNS, DTE_MAXES):
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    params.update(BASE)
    params["start_date"]          = start
    params["end_date"]            = end
    params["entry_cooldown_days"] = cooldown
    params["dte_max"]             = dte_max
    params["dte_min"]             = DTE_MIN_BY_DTE_MAX[dte_max]

    engine = None
    try:
        data   = load_market_data(start, end, market="bova11")
        engine = make_engine(params)
        trades, equity_df, portfolio, _ = run_portfolio_backtest(data, params, engine)
        metrics = compute_portfolio_metrics(trades, equity_df, params, data)
        rows.append({
            "period_label":        period_label,
            "entry_cooldown_days": cooldown,
            "dte_max":             dte_max,
            "dte_min":             DTE_MIN_BY_DTE_MAX[dte_max],
            "sharpe":              metrics.get("info_ratio") or metrics.get("sharpe"),
            "total_return":        metrics.get("tot"),
            "annualized_return":   metrics.get("ann"),
            "max_drawdown":        metrics.get("mdd"),
            "calmar":              metrics.get("calmar"),
            "n_trades":            metrics.get("n"),
            "win_rate":            metrics.get("wr"),
            "avg_bpr_util":        metrics.get("avg_bpr_util"),
            "peak_bpr_util":       metrics.get("peak_bpr_util"),
            "avg_positions":       metrics.get("avg_positions"),
            "peak_positions":      metrics.get("peak_positions"),
        })
        print(
            f"  [{period_label}] cooldown={cooldown} dte_max={dte_max} → "
            f"IR={rows[-1]['sharpe']:.3f}  n={rows[-1]['n_trades']}  "
            f"avg_bpr={rows[-1]['avg_bpr_util']:.1f}%"
        )
    except Exception as e:
        print(f"  ERROR [{period_label}] cooldown={cooldown} dte_max={dte_max}: {e}")
        rows.append({
            "period_label":        period_label,
            "entry_cooldown_days": cooldown,
            "dte_max":             dte_max,
            "error":               str(e),
        })
    finally:
        if engine is not None and hasattr(engine, "close"):
            engine.close()

df  = pd.DataFrame(rows)
out = ROOT / "data" / "B3" / "v7_cooldown_sensitivity.parquet"
df.to_parquet(out, index=False)
print(f"\nSaved {len(df)} rows to {out}")
