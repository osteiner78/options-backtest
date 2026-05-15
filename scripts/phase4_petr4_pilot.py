"""Phase 4: PETR4 pilot — 18 backtests (3 configs × 3 modes × 2 periods).

Decision gate:
- If mid holdout median > 0: proceed to full grid
- If bid_ask <= -0.50 AND mid <= -0.20 AND mid_plus_1tick <= 0.10: skip full grid
"""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics
from grid_search import _apply_vol_filter, DTE_MIN_BY_DTE_MAX

CONFIGS = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14,
     "vix_filter": "OFF"},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14,
     "vix_filter": "rv_pct:80"},
    {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14,
     "vix_filter": "rv_pct:70"},
]
MODES = ["bid_ask", "mid", "mid_plus_1tick"]
PERIODS = [
    ("train",   "2018-01-02", "2022-12-30"),
    ("holdout", "2023-01-02", "2025-11-30"),
]


def build_params(config: dict, mode: str, start: str, end: str) -> dict:
    params = dict(PARAMS)
    params = apply_market_preset(params, "petr4")
    overrides = _apply_vol_filter(config["vix_filter"], {})
    overrides.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "target_delta": config["target_delta"],
        "dte_max": config["dte_max"],
        "dte_min": DTE_MIN_BY_DTE_MAX[config["dte_max"]],
        "profit_target_pct": config["profit_target_pct"],
        "manage_at_dte": config["manage_at_dte"],
        "stop_loss_pct": 2.0,
        "use_price_stop": True,
        "execution_mode": mode,
        "portfolio_mode": "laddering",
        "single_position": False,
    })
    params.update(overrides)
    return params


print("=== Phase 4: PETR4 Pilot (18 backtests) ===\n", flush=True)
results = []

# Load data once per period
data_cache = {}
for period, start, end in PERIODS:
    print(f"Loading PETR4 data for {period}...", flush=True)
    try:
        data_cache[period] = load_market_data(start, end, market="petr4")
        print(f"  Loaded: {len(data_cache[period])} rows")
    except Exception as e:
        print(f"  Error loading data: {e}")
        data_cache[period] = None

for ci, config in enumerate(CONFIGS, 1):
    cfg_label = f"δ={config['target_delta']}/dte{config['dte_max']}/pt{int(config['profit_target_pct']*100)}%/{config['vix_filter']}"
    print(f"\nConfig {ci}: {cfg_label}", flush=True)

    for period, start, end in PERIODS:
        data = data_cache.get(period)
        if data is None:
            print(f"  {period}: data unavailable, skipping")
            continue

        for mode in MODES:
            try:
                params = build_params(config, mode, start, end)
                engine = make_engine(params)
                trades, eq_df, pm, _ = run_portfolio_backtest(data, params, engine, progress=False)
                metrics = compute_portfolio_metrics(trades, eq_df, params, data)
                sharpe = metrics.get("sharpe", float("nan"))
                n = metrics.get("n", 0)
                tot = metrics.get("tot", 0.0)
                results.append({
                    "config": ci, "target_delta": config["target_delta"],
                    "dte_max": config["dte_max"], "vix_filter": config["vix_filter"],
                    "mode": mode, "period": period,
                    "sharpe": sharpe, "n_trades": n, "total_return": tot,
                })
                print(f"  {period:8s} {mode:16s} n={n:3d} sharpe={sharpe:7.3f} return={tot:.4f}")
            except Exception as e:
                print(f"  {period:8s} {mode:16s} ERROR: {e}")
                results.append({
                    "config": ci, "target_delta": config["target_delta"],
                    "dte_max": config["dte_max"], "vix_filter": config["vix_filter"],
                    "mode": mode, "period": period,
                    "sharpe": float("nan"), "n_trades": 0, "total_return": 0.0,
                })

# Summary
print("\n\n=== Summary: Median Sharpe by Mode and Period ===")
df_res = pd.DataFrame(results)
if len(df_res) > 0:
    pivot = df_res.groupby(["mode", "period"])["sharpe"].median().unstack()
    print(pivot.round(3).to_string())

    print("\n=== Decision Gate ===")
    holdout = df_res[df_res["period"] == "holdout"]
    for mode in MODES:
        mode_rows = holdout[holdout["mode"] == mode]
        if len(mode_rows) > 0:
            med = mode_rows["sharpe"].median()
            print(f"  {mode:16s} holdout median Sharpe: {med:.3f}")

    mid_holdout_median = holdout[holdout["mode"] == "mid"]["sharpe"].median()
    ba_holdout_median  = holdout[holdout["mode"] == "bid_ask"]["sharpe"].median()
    mp_holdout_median  = holdout[holdout["mode"] == "mid_plus_1tick"]["sharpe"].median()

    print()
    if mid_holdout_median > 0:
        print(f"  PROCEED: mid holdout median {mid_holdout_median:.3f} > 0 → run full PETR4 grid")
    elif (ba_holdout_median <= -0.50 and mid_holdout_median <= -0.20 and mp_holdout_median <= 0.10):
        print(f"  SKIP: bid_ask={ba_holdout_median:.3f} ≤ -0.50, mid={mid_holdout_median:.3f} ≤ -0.20, "
              f"mid+1tick={mp_holdout_median:.3f} ≤ 0.10 → PETR4 VRP not capturable")
    else:
        print(f"  BORDERLINE: mid={mid_holdout_median:.3f}. Manual review needed.")
