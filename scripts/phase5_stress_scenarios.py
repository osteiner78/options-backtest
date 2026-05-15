"""Phase 5: Max-drawdown stress scenarios.

Steps:
  5.1 - Worst 6-month (120-trading-day) rolling windows for 25Δ, 16Δ, 12Δ configs
  5.2 - Gap-event stress: dates where MTM equity dropped >5% in a single day
  5.3 - Report summary table
"""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from pathlib import Path
from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics, _compute_mtm_equity
from grid_search import _apply_vol_filter, DTE_MIN_BY_DTE_MAX

OUT_PATH = Path("data/B3/v7_stress_scenarios.csv")

# Three configs from the plan
CONFIGS = [
    {"label": "25δ/mid",        "target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",        "stop_loss_pct": 2.0, "execution_mode": "mid"},
    {"label": "16δ/mid",        "target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:70",  "stop_loss_pct": 3.0, "execution_mode": "mid"},
    {"label": "12δ/mid+1tick",  "target_delta": 0.12, "dte_max": 30, "profit_target_pct": 0.25,
     "manage_at_dte": 7,  "vix_filter": "rv_pct:80",  "stop_loss_pct": 3.0, "execution_mode": "mid_plus_1tick"},
]

# Use full available period: train + holdout combined
START = "2018-01-02"
END   = "2025-11-30"
WINDOW = 120  # trading days ~ 6 months


def build_params(config: dict, start: str, end: str) -> dict:
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    overrides = _apply_vol_filter(config["vix_filter"], {})
    overrides.update({
        "mode": "market", "start_date": start, "end_date": end,
        "target_delta": config["target_delta"],
        "dte_max": config["dte_max"],
        "dte_min": DTE_MIN_BY_DTE_MAX[config["dte_max"]],
        "profit_target_pct": config["profit_target_pct"],
        "manage_at_dte": config["manage_at_dte"],
        "stop_loss_pct": config["stop_loss_pct"],
        "use_price_stop": True,
        "execution_mode": config["execution_mode"],
        "portfolio_mode": "laddering",
        "single_position": False,
    })
    params.update(overrides)
    return params


def get_mtm_equity(trades: list, params: dict) -> pd.Series:
    """Build MTM equity from trade daily_marks."""
    init = float(params.get("initial_balance", 50_000))
    records = []
    for t in trades:
        for date, mark in (getattr(t, "daily_marks", []) or []):
            records.append({"date": date, "trade": t.trade_num, "mark": mark})
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records).sort_values(["trade", "date"])
    df["prev"] = df.groupby("trade")["mark"].shift(1).fillna(0.0)
    df["delta"] = df["mark"] - df["prev"]
    daily_pnl = df.groupby("date")["delta"].sum().sort_index()
    return init + daily_pnl.cumsum()


def rolling_6m_windows(equity: pd.Series, window: int = 120) -> pd.DataFrame:
    """Compute all rolling 6-month windows."""
    if len(equity) < window:
        return pd.DataFrame()
    rows = []
    for i in range(len(equity) - window + 1):
        seg = equity.iloc[i:i + window]
        start_dt = seg.index[0]
        end_dt   = seg.index[-1]
        init_val = seg.iloc[0]
        final_val = seg.iloc[-1]
        seg_ret = (final_val - init_val) / init_val if init_val > 0 else float("nan")
        # Max intra-window MTM drawdown
        pk = np.maximum.accumulate(seg.values)
        intra_mdd = float(((seg.values - pk) / pk).min()) if len(seg) else 0.0
        rows.append({
            "window_start": start_dt, "window_end": end_dt,
            "period_return": seg_ret, "intra_mdd": intra_mdd,
        })
    return pd.DataFrame(rows)


print("=== Phase 5: Stress Scenario Analysis ===\n", flush=True)
all_stress_rows = []
gap_events_all = []

data_full = load_market_data(START, END, market="bova11")

for config in CONFIGS:
    label = config["label"]
    print(f"Running config: {label}", flush=True)
    params = build_params(config, START, END)
    engine = make_engine(params)
    trades, eq_df, pm, _ = run_portfolio_backtest(data_full, params, engine, progress=False)

    mtm = get_mtm_equity(trades, params)
    if mtm.empty:
        print(f"  No equity curve — skipping")
        continue
    print(f"  n_trades={len(trades)}, equity range: {mtm.index[0].date()} to {mtm.index[-1].date()}")

    # ── Step 5.1: Worst 6-month windows ─────────────────────────────────
    windows_df = rolling_6m_windows(mtm, WINDOW)
    if len(windows_df) == 0:
        print(f"  Not enough data for 6-month windows")
        continue

    worst3 = windows_df.nsmallest(3, "period_return")
    print(f"\n  Worst 3 six-month windows (by total P&L return):")
    print(f"  {'Start':<12} {'End':<12} {'Return':>10} {'Intra MDD':>12}")
    print("  " + "-"*50)
    for _, r in worst3.iterrows():
        print(f"  {str(r['window_start'].date()):<12} {str(r['window_end'].date()):<12} "
              f"{r['period_return']:10.2%} {r['intra_mdd']:12.2%}")
        all_stress_rows.append({
            "config": label,
            "window_start": r["window_start"].date(),
            "window_end": r["window_end"].date(),
            "period_return": round(r["period_return"], 6),
            "intra_mdd": round(r["intra_mdd"], 6),
        })

    # ── Step 5.2: Gap events (MTM daily drop >5%) ─────────────────────────
    daily_pnl = mtm.diff().dropna()
    init = float(params.get("initial_balance", 50_000))
    daily_ret = daily_pnl / init

    big_drops = daily_ret[daily_ret < -0.05]
    if len(big_drops) > 0:
        print(f"\n  Gap events (MTM equity daily drop >5%): {len(big_drops)}")
        for drop_date, drop_pct in big_drops.items():
            # Find open trades on this date
            open_trades = [t for t in trades
                           if t.entry_date <= drop_date and
                           (t.exit_date is None or t.exit_date >= drop_date)]
            print(f"    {drop_date.date()}: {drop_pct:.2%} — {len(open_trades)} open positions "
                  f"(exits: {[t.exit_type for t in open_trades if t.exit_date == drop_date]})")
            gap_events_all.append({
                "config": label,
                "drop_date": drop_date.date(),
                "daily_return": round(float(drop_pct), 6),
                "n_open_trades": len(open_trades),
            })
    else:
        print(f"\n  No gap events (MTM equity daily drop >5%) found.")

# Save stress results
df_stress = pd.DataFrame(all_stress_rows)
df_stress.to_csv(OUT_PATH, index=False)
print(f"\n\nStress scenarios saved to {OUT_PATH} ({len(df_stress)} rows)")

# ── Step 5.3: Summary table ────────────────────────────────────────────────
print("\n=== Step 5.3: Summary Table — Worst 3 Windows per Config ===\n")
if len(df_stress) > 0:
    print(f"{'Config':<20} {'Window Start':<13} {'Window End':<13} {'Return':>10} {'Intra MDD':>12}")
    print("-" * 72)
    for _, r in df_stress.iterrows():
        print(f"  {r['config']:<18} {str(r['window_start']):<13} {str(r['window_end']):<13} "
              f"{r['period_return']:10.2%} {r['intra_mdd']:12.2%}")

print("\n=== Gap Events Summary ===")
if gap_events_all:
    df_gaps = pd.DataFrame(gap_events_all)
    print(df_gaps.to_string(index=False))
else:
    print("No gap events (>5% daily MTM drop) detected in any config.")
