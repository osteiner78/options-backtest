#!/usr/bin/env python3
"""DTE30 cooldown deep-dive for BOVA11 recommended config.

Fixed base: 25Δ/dte30/OFF/stop2.0/mid/laddering
Sensitivity: entry_cooldown_days × manage_at_dte × profit_target_pct × period
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

COOLDOWNS      = [1, 2, 3, 5, 7]
MANAGE_DTES    = [5, 7, 14]
PROFIT_TARGETS = [0.25, 0.50]

PERIODS = [
    ("train",   "2018-01-02", "2022-12-30"),
    ("holdout", "2023-01-02", "2025-11-30"),
]

BASE = {
    "target_delta":             0.25,
    "dte_max":                  30,
    "dte_min":                  20,
    "vix_entry_filter_enabled": False,
    "stop_loss_pct":            2.0,
    "execution_mode":           "mid",
    "portfolio_mode":           "laddering",
    "mode":                     "market",
}

rows = []
combos = list(product(PERIODS, COOLDOWNS, MANAGE_DTES, PROFIT_TARGETS))
print(f"Running {len(combos)} backtests...")

for (period_label, start, end), cooldown, manage_dte, pt_pct in combos:
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    params.update(BASE)
    params["start_date"]          = start
    params["end_date"]            = end
    params["entry_cooldown_days"] = cooldown
    params["manage_at_dte"]       = manage_dte
    params["profit_target_pct"]   = pt_pct

    engine = None
    try:
        data    = load_market_data(start, end, market="bova11")
        engine  = make_engine(params)
        trades, equity_df, portfolio, _ = run_portfolio_backtest(data, params, engine)
        metrics = compute_portfolio_metrics(trades, equity_df, params, data)
        rows.append({
            "period_label":        period_label,
            "entry_cooldown_days": cooldown,
            "manage_at_dte":       manage_dte,
            "profit_target_pct":   pt_pct,
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
            f"  [{period_label}] cd={cooldown} mgr={manage_dte} pt={pt_pct:.0%} → "
            f"IR={rows[-1]['sharpe']:.3f}  n={rows[-1]['n_trades']}  "
            f"avg_bpr={rows[-1]['avg_bpr_util']:.1f}%"
        )
    except Exception as e:
        print(f"  ERROR [{period_label}] cd={cooldown} mgr={manage_dte} pt={pt_pct}: {e}")
        rows.append({
            "period_label":        period_label,
            "entry_cooldown_days": cooldown,
            "manage_at_dte":       manage_dte,
            "profit_target_pct":   pt_pct,
            "error":               str(e),
        })
    finally:
        if engine is not None and hasattr(engine, "close"):
            engine.close()

df  = pd.DataFrame(rows)
out = ROOT / "data" / "B3" / "v7_dte30_deep_dive.parquet"
df.to_parquet(out, index=False)
print(f"\nSaved {len(df)} rows to {out}")
