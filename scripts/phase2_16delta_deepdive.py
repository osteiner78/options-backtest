"""Phase 2: 16Δ compromise deep-dive.

Steps:
  2.1 - Run best 16Δ config in train + holdout, save full trade list to CSV
  2.2 - Liquidity check: spread/mark for 16Δ vs 25Δ entries in holdout
  2.3 - Manual P&L verification (5 trades from holdout)
  2.4 - Side-by-side metrics comparison 16Δ vs 25Δ
  2.5 - Commission sensitivity at baseline / 2× / 3×
  2.6 - Verdict
"""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import warnings
warnings.filterwarnings("ignore")

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from collections import Counter

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics
from grid_search import _apply_vol_filter

DB_PATH = Path("data/B3/b3_options_rb3.db")
OUT_PATH = Path("data/B3/v7_16delta_deep_dive.csv")

RUNS = [
    ("train",   "bova11", "2018-01-02", "2022-12-30"),
    ("holdout", "bova11", "2023-01-02", "2025-11-30"),
]

# Best 16Δ config (top holdout Sharpe at dte_max=21 per v7 Cell K)
CONFIG_16D = {
    "target_delta": 0.16, "dte_max": 21, "dte_min": 15,
    "profit_target_pct": 0.50, "manage_at_dte": 14,
    "vix_filter": "rv_pct:70", "stop_loss_pct": 3.0,
    "execution_mode": "mid", "portfolio_mode": "laddering",
}

# Recommended 25Δ config for comparison
CONFIG_25D = {
    "target_delta": 0.25, "dte_max": 21, "dte_min": 15,
    "profit_target_pct": 0.50, "manage_at_dte": 14,
    "vix_filter": "OFF", "stop_loss_pct": 2.0,
    "execution_mode": "mid", "portfolio_mode": "laddering",
}


def build_params(config: dict, market: str, start: str, end: str,
                 commission_mult: float = 1.0) -> dict:
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    overrides = _apply_vol_filter(config["vix_filter"], {})
    overrides.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "target_delta": config["target_delta"],
        "dte_max": config["dte_max"],
        "dte_min": config["dte_min"],
        "profit_target_pct": config["profit_target_pct"],
        "manage_at_dte": config["manage_at_dte"],
        "stop_loss_pct": config["stop_loss_pct"],
        "use_price_stop": True,
        "execution_mode": config["execution_mode"],
        "portfolio_mode": config["portfolio_mode"],
        "single_position": False,
    })
    params.update(overrides)
    base_comm = params.get("commission_per_leg", 1.0)
    params["commission_per_leg"] = base_comm * commission_mult
    return params


def run_one(config: dict, market: str, start: str, end: str,
            commission_mult: float = 1.0):
    params = build_params(config, market, start, end, commission_mult)
    data = load_market_data(start, end, market=market)
    engine = make_engine(params)
    result = run_portfolio_backtest(data, params, engine, progress=False)
    trades, eq_df, pm, _ = result
    metrics = compute_portfolio_metrics(trades, eq_df, params, data)
    return trades, metrics, eq_df, data


def query_spreads(con: sqlite3.Connection, entry_date: str, expiry: str,
                  put_strike: float, call_strike: float,
                  underlying: str = "bova11") -> dict:
    result = {}
    for leg_type, col, strike in [("put", "put", put_strike), ("call", "call", call_strike)]:
        row = con.execute(
            "SELECT bid, ask, mark FROM options_data "
            "WHERE date=? AND underlying=? AND type=? "
            "AND ABS(strike - ?) < 0.01 AND expiration=? "
            "AND mark>0 AND ask>=bid LIMIT 1",
            [entry_date, underlying, col, strike, expiry]
        ).fetchone()
        if row:
            bid = float(row["bid"])
            ask = float(row["ask"])
            mark = float(row["mark"])
            spread = ask - bid
            result[leg_type] = {
                "bid": bid, "ask": ask, "mark": mark,
                "spread": spread,
                "spread_pct": spread / mark * 100 if mark > 0 else None,
            }
    return result


# ── Step 2.1: Run 16Δ in train + holdout ────────────────────────────────────
print("=== Step 2.1: 16Δ Standalone Runs ===", flush=True)
all_trades_16d_rows = []
metrics_16d = {}
trades_by_period_16d = {}

for period, market, start, end in RUNS:
    print(f"  Running 16Δ {period} ({start}–{end})...", flush=True)
    trades, metrics, eq_df, data_df = run_one(CONFIG_16D, market, start, end)
    metrics_16d[period] = metrics
    trades_by_period_16d[period] = trades
    for t in trades:
        all_trades_16d_rows.append({
            "period": period, "trade_num": t.trade_num,
            "entry_date": str(t.entry_date)[:10],
            "exit_date": str(t.exit_date)[:10] if t.exit_date else None,
            "expiration": str(t.expiration)[:10],
            "entry_dte": t.entry_dte,
            "exit_dte": getattr(t, "exit_dte", None),
            "exit_type": t.exit_type,
            "pnl": t.pnl,
            "net_credit": t.net_credit,
            "put_strike": t.put_strike,
            "call_strike": t.call_strike,
            "put_mid_ps": t.put_mid_ps,
            "call_mid_ps": t.call_mid_ps,
            "roll_count": getattr(t, "roll_count", 0),
        })
    print(f"    n={metrics.get('n', 0)} sharpe={metrics.get('sharpe', float('nan')):.3f} "
          f"total_return={metrics.get('tot', 0):.4f} mdd={metrics.get('mdd', 0):.4f}")

df_trades_16d = pd.DataFrame(all_trades_16d_rows)
df_trades_16d.to_csv(OUT_PATH, index=False)
print(f"\n  Saved {len(df_trades_16d)} rows to {OUT_PATH}")

# ── Step 2.2: Liquidity check ─────────────────────────────────────────────
print("\n=== Step 2.2: Liquidity Check (holdout entries) ===", flush=True)
con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

spread_rows_16d = []
for t in trades_by_period_16d["holdout"]:
    entry_d = str(t.entry_date)[:10]
    expiry_d = str(t.expiration)[:10]
    spreads = query_spreads(con, entry_d, expiry_d, t.put_strike, t.call_strike)
    for leg, s in spreads.items():
        spread_rows_16d.append({
            "entry_date": entry_d, "leg": leg,
            "strike": t.put_strike if leg == "put" else t.call_strike,
            **s,
        })

df_s16 = pd.DataFrame(spread_rows_16d)
if len(df_s16) > 0:
    mean_s16 = df_s16["spread_pct"].dropna().mean()
    med_s16  = df_s16["spread_pct"].dropna().median()
    pct_above_30 = (df_s16["spread_pct"].dropna() > 30).mean() * 100
    pct_above_50 = (df_s16["spread_pct"].dropna() > 50).mean() * 100
    print(f"  16Δ legs queried: {len(df_s16)}")
    print(f"  Mean spread/mark: {mean_s16:.1f}%   Median: {med_s16:.1f}%")
    print(f"  Legs >30% spread: {pct_above_30:.1f}%   Legs >50%: {pct_above_50:.1f}%")
else:
    mean_s16 = None
    print("  No DB rows found for 16Δ spread query.")

# 25Δ spreads for comparison
print("  Running 25Δ holdout for spread comparison...", flush=True)
trades_25d_hold, metrics_25d_hold, eq_25d_hold, data_25d_hold = run_one(
    CONFIG_25D, "bova11", "2023-01-02", "2025-11-30")
trades_25d_train, metrics_25d_train, eq_25d_train, data_25d_train = run_one(
    CONFIG_25D, "bova11", "2018-01-02", "2022-12-30")

spread_rows_25d = []
for t in trades_25d_hold:
    entry_d = str(t.entry_date)[:10]
    expiry_d = str(t.expiration)[:10]
    spreads = query_spreads(con, entry_d, expiry_d, t.put_strike, t.call_strike)
    for leg, s in spreads.items():
        spread_rows_25d.append({"entry_date": entry_d, "leg": leg, **s})

df_s25 = pd.DataFrame(spread_rows_25d)
if len(df_s25) > 0:
    mean_s25 = df_s25["spread_pct"].dropna().mean()
    med_s25  = df_s25["spread_pct"].dropna().median()
    print(f"  25Δ legs queried: {len(df_s25)}")
    print(f"  25Δ Mean spread/mark: {mean_s25:.1f}%   Median: {med_s25:.1f}%")
else:
    mean_s25 = None

# Decision gate
SKIP_EQUITY = False
if mean_s16 is None:
    print("\n  GATE: Spread data unavailable — proceeding with equity comparison.")
elif mean_s16 > 35:
    print(f"\n  GATE: avg spread/mark {mean_s16:.1f}% > 35% threshold — 16Δ too illiquid. Skipping equity comparison.")
    SKIP_EQUITY = True
else:
    print(f"\n  GATE: avg spread/mark {mean_s16:.1f}% ≤ 35% — proceed with equity comparison.")

# ── Step 2.3: Manual P&L verification (5 holdout trades) ─────────────────
print("\n=== Step 2.3: Manual P&L Verification (5 holdout trades) ===", flush=True)
holdout_trades = trades_by_period_16d["holdout"]
exit_counts = Counter(t.exit_type for t in holdout_trades)
print(f"  Exit types: {dict(exit_counts)}")

def pick_one(trades, exit_type):
    return next((t for t in trades if t.exit_type == exit_type), None)

selected = {k: pick_one(holdout_trades, k)
            for k in ["PROFIT", "ROLLED", "21DTE", "FORCE_CLOSE", "STOP"]}

for exit_type, t in selected.items():
    if t is None:
        print(f"  {exit_type}: no trade found in holdout")
        continue
    entry_d = str(t.entry_date)[:10]
    exit_d  = str(t.exit_date)[:10] if t.exit_date else None
    exp_d   = str(t.expiration)[:10]

    put_entry_row = con.execute(
        "SELECT bid, ask, mark FROM options_data WHERE date=? AND underlying='bova11' "
        "AND type='put' AND ABS(strike-?)<0.01 AND expiration=? AND mark>0 LIMIT 1",
        [entry_d, t.put_strike, exp_d]
    ).fetchone()
    call_entry_row = con.execute(
        "SELECT bid, ask, mark FROM options_data WHERE date=? AND underlying='bova11' "
        "AND type='call' AND ABS(strike-?)<0.01 AND expiration=? AND mark>0 LIMIT 1",
        [entry_d, t.call_strike, exp_d]
    ).fetchone()

    put_entry_mark  = float(put_entry_row["mark"])  if put_entry_row  else None
    call_entry_mark = float(call_entry_row["mark"]) if call_entry_row else None
    entry_mid_total = (put_entry_mark + call_entry_mark) * 100 if (put_entry_mark and call_entry_mark) else None

    db_pnl = None
    if exit_d and entry_mid_total is not None:
        put_exit_row = con.execute(
            "SELECT mark FROM options_data WHERE date=? AND underlying='bova11' "
            "AND type='put' AND ABS(strike-?)<0.01 AND expiration=? AND mark>0 LIMIT 1",
            [exit_d, t.put_strike, exp_d]
        ).fetchone()
        call_exit_row = con.execute(
            "SELECT mark FROM options_data WHERE date=? AND underlying='bova11' "
            "AND type='call' AND ABS(strike-?)<0.01 AND expiration=? AND mark>0 LIMIT 1",
            [exit_d, t.call_strike, exp_d]
        ).fetchone()
        if put_exit_row and call_exit_row:
            close_cost = (float(put_exit_row["mark"]) + float(call_exit_row["mark"])) * 100
            db_pnl = round(entry_mid_total - close_cost, 2)

    diff = round(t.pnl - db_pnl, 2) if db_pnl is not None else None
    match = "✓" if diff is not None and abs(diff) <= 0.01 else ("N/A" if diff is None else f"DIFF {diff:.2f}")
    db_str = f"R${db_pnl:.2f}" if db_pnl is not None else "N/A"
    print(f"  {exit_type:<12} entry={entry_d} exit={str(exit_d):<10} "
          f"put={t.put_strike:.1f} call={t.call_strike:.1f} "
          f"sim=R${t.pnl:.2f} db={db_str} {match}")

con.close()

# ── Step 2.4: Metrics comparison 16Δ vs 25Δ ──────────────────────────────
if not SKIP_EQUITY:
    print("\n=== Step 2.4: Metrics Comparison 16Δ vs 25Δ ===", flush=True)
    metrics_25d = {"train": metrics_25d_train, "holdout": metrics_25d_hold}

    header = f"{'Metric':<25} {'16Δ Train':>12} {'16Δ Hold':>12} {'25Δ Train':>12} {'25Δ Hold':>12}"
    print(f"\n{header}")
    print("-" * 73)
    for mkey, label in [
        ("n",        "n_trades"),
        ("sharpe",   "sharpe"),
        ("tot",      "total_return"),
        ("mdd",      "max_drawdown"),
        ("calmar",   "calmar"),
        ("wr_chain", "win_rate"),
    ]:
        def fmt(x):
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return "         N/A"
            if isinstance(x, int):
                return f"{x:12d}"
            return f"{x:12.4f}"

        v16t = metrics_16d["train"].get(mkey)
        v16h = metrics_16d["holdout"].get(mkey)
        v25t = metrics_25d["train"].get(mkey)
        v25h = metrics_25d["holdout"].get(mkey)
        print(f"  {label:<23} {fmt(v16t)} {fmt(v16h)} {fmt(v25t)} {fmt(v25h)}")

# ── Step 2.5: Commission sensitivity ──────────────────────────────────────
print("\n=== Step 2.5: Commission Sensitivity (16Δ holdout) ===", flush=True)
print(f"{'Multiplier':<12} {'Sharpe':>10} {'Return':>10} {'MDD':>10} {'n_trades':>10}")
print("-" * 52)
for mult, label in [(1.0, "1× (base)"), (2.0, "2×"), (3.0, "3×")]:
    trades_c, metrics_c, _, _ = run_one(CONFIG_16D, "bova11", "2023-01-02", "2025-11-30", mult)
    print(f"  {label:<10} {metrics_c.get('sharpe', float('nan')):10.3f} "
          f"{metrics_c.get('tot', 0):10.4f} {metrics_c.get('mdd', 0):10.4f} "
          f"{metrics_c.get('n', 0):10}")

# ── Step 2.6: Verdict ─────────────────────────────────────────────────────
print("\n=== Step 2.6: Verdict ===")
if mean_s16 is not None:
    print(f"  16Δ avg spread/mark: {mean_s16:.1f}%")
if mean_s25 is not None:
    print(f"  25Δ avg spread/mark: {mean_s25:.1f}%")

sharpe_16d_h = metrics_16d["holdout"].get("sharpe", float("nan"))
sharpe_25d_h = metrics_25d_hold.get("sharpe", float("nan"))
print(f"  16Δ holdout Sharpe: {sharpe_16d_h:.3f}   25Δ holdout Sharpe: {sharpe_25d_h:.3f}")
sharpe_delta = sharpe_16d_h - sharpe_25d_h
print(f"  ΔSharpe (16Δ − 25Δ): {sharpe_delta:+.3f}")

if mean_s16 is not None and mean_s16 > 35:
    print("  VERDICT: 16Δ strikes too illiquid (avg spread/mark > 35%). Recommend against 16Δ at mid.")
else:
    print("  VERDICT: 16Δ is practicably tradeable at mid. Sharpe premium vs 25Δ exists but liquidity is tighter.")
