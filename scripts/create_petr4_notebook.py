"""Create the PETR4 grid notebook template."""
import json
import uuid


def make_id():
    return str(uuid.uuid4())[:8]


def md_cell(source):
    return {
        "id": make_id(), "cell_type": "markdown",
        "metadata": {}, "source": source,
    }


def code_cell(source):
    return {
        "id": make_id(), "cell_type": "code",
        "metadata": {}, "source": source,
        "outputs": [], "execution_count": None,
    }


IMPORTS = """\
%matplotlib inline
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

plt.rcParams['figure.dpi'] = 120
plt.rcParams['figure.figsize'] = (12, 5)

ROOT = Path.cwd().parent if (Path.cwd().name == 'research') else Path.cwd()
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
from grid_search import run_grid, enumerate_grid, GRID_DIMS, DTE_MIN_BY_DTE_MAX

OUT_DIR      = ROOT / 'data' / 'B3'
RESULTS_PATH = OUT_DIR / 'v7_petr4_grid_search_results.parquet'
DB_PATH      = ROOT / 'data' / 'B3' / 'b3_options_rb3.db'\
"""

GRID_DEF = """\
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
combos = enumerate_grid(GRID)
print(f"Grid: {len(combos)} valid combos x 2 periods = {len(combos) * 2} backtests")\
"""

RUNS_CELL = """\
RUNS = [
    ("train",   "petr4", "2018-01-02", "2022-12-30"),
    ("holdout", "petr4", "2023-01-02", "2025-11-30"),
]
for r in RUNS:
    print(r)\
"""

EXECUTE_CELL = """\
from straddle.strategy import clear_vol_cache

clear_vol_cache()

if RESULTS_PATH.exists():
    print(f"Loading cached results from {RESULTS_PATH}")
    results = pd.read_parquet(RESULTS_PATH)
else:
    results = run_grid(GRID, RUNS, output_path=RESULTS_PATH)
    print(f"Saved {len(results)} rows to {RESULTS_PATH}")

df = results[results["error"].isna() & (results["n_trades"] >= 30)].copy()
df["execution_mode"] = pd.Categorical(
    df["execution_mode"],
    categories=["bid_ask", "mid", "mid_plus_1tick"],
    ordered=True,
)
df["delta_label"] = df["target_delta"].apply(lambda x: f"{int(x*100)}\\u0394")

train   = df[df["period_label"] == "train"]
holdout = df[df["period_label"] == "holdout"]
modes   = ["bid_ask", "mid", "mid_plus_1tick"]

print(f"Total rows: {len(results):,} | valid: {len(df):,}")
print(f"Train rows: {len(train):,} | Holdout rows: {len(holdout):,}")
print(f"Error rate: {results['error'].notna().sum() / len(results):.1%}")\
"""

CELL_A = """\
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
for ax, period_df, title in [
    (axes[0], train, "Train (2018-2022)"),
    (axes[1], holdout, "Holdout (2023-2025)"),
]:
    data_by_mode = [
        period_df[period_df["execution_mode"] == m]["sharpe"] for m in modes
    ]
    ax.boxplot(data_by_mode, labels=modes, notch=False, sym="")
    ax.axhline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel("Sharpe ratio")
    ax.set_xlabel("Execution mode")
plt.suptitle("Cell A: PETR4 Sharpe by Execution Mode", fontsize=13)
plt.tight_layout()
plt.show()

print("Holdout median Sharpe by execution mode:")
for m in modes:
    sub = holdout[holdout["execution_mode"] == m]["sharpe"]
    pct_pos = (sub > 0).mean()
    print(f"  {m:<20} median={sub.median():.3f}  pct_positive={pct_pos:.1%}  n={len(sub)}")\
"""

CELL_B = """\
key_cols = [c for c in GRID_DIMS if c in df.columns and c != "execution_mode"]
joined = holdout.pivot_table(index=key_cols, columns="execution_mode", values="sharpe")
joined.columns = [f"sharpe_{c}" for c in joined.columns]
joined = joined.reset_index()

breakeven = []
for _, row in joined.iterrows():
    if row.get("sharpe_bid_ask", -999) > 0:
        breakeven.append("bid_ask")
    elif row.get("sharpe_mid", -999) > 0:
        breakeven.append("mid")
    elif row.get("sharpe_mid_plus_1tick", -999) > 0:
        breakeven.append("mid_plus_1tick")
    else:
        breakeven.append("none")
joined["break_even"] = breakeven

print("Break-even execution level (PETR4 holdout):")
print(joined["break_even"].value_counts().to_string())
print(f"Viable at mid or better: {(joined['break_even'].isin(['bid_ask','mid'])).mean():.1%}")
print(f"Viable at mid_plus_1tick only: {(joined['break_even'] == 'mid_plus_1tick').mean():.1%}")
print(f"Not viable at any level: {(joined['break_even'] == 'none').mean():.1%}")\
"""

CELL_C = """\
pivot = holdout.pivot_table(
    values="sharpe", index="delta_label", columns="execution_mode", aggfunc="median"
)
fig, ax = plt.subplots(figsize=(8, 4))
im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=-1, vmax=3, aspect="auto")
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels(pivot.columns, rotation=30)
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index)
for i in range(len(pivot.index)):
    for j in range(len(pivot.columns)):
        ax.text(j, i, f"{pivot.values[i, j]:.2f}", ha="center", va="center", fontsize=9)
plt.colorbar(im, ax=ax, label="Median Sharpe")
ax.set_title("Cell C: PETR4 Delta x Execution Mode — Holdout")
plt.tight_layout()
plt.show()\
"""

CELL_D = """\
key_cols_nomode = [
    c for c in GRID_DIMS
    if c in df.columns and c not in ("execution_mode", "period_label")
]
t_sh = train[["sharpe", "execution_mode"] + key_cols_nomode].rename(columns={"sharpe": "sharpe_t"})
h_sh = holdout[["sharpe", "execution_mode"] + key_cols_nomode].rename(columns={"sharpe": "sharpe_h"})
merge_key = ["execution_mode"] + key_cols_nomode
joined2 = t_sh.merge(h_sh, on=merge_key, how="inner")
joined2["min_sharpe"] = joined2[["sharpe_t", "sharpe_h"]].min(axis=1)
stability = joined2.sort_values("min_sharpe", ascending=False)

print("Top 10 configs by min(train_sharpe, holdout_sharpe) - mid:")
top10_mid = stability[stability["execution_mode"] == "mid"].head(10)
display_cols = merge_key + ["sharpe_t", "sharpe_h", "min_sharpe"]
print(top10_mid[display_cols].to_string(index=False))

print("\\nTop 10 configs - mid_plus_1tick:")
top10_mpt = stability[stability["execution_mode"] == "mid_plus_1tick"].head(10)
print(top10_mpt[display_cols].to_string(index=False))\
"""

CELL_E = """\
# Compare PETR4 vs BOVA11 for the recommended 25delta/dte21/pt50%/OFF/mid config
bova11_df = pd.read_parquet(OUT_DIR / "v7_grid_search_results.parquet")

ref = {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
       "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0, "execution_mode": "mid"}

def filter_config(df, config):
    mask = pd.Series([True] * len(df), index=df.index)
    for k, v in config.items():
        if k in df.columns:
            mask &= (df[k] == v)
    return df[mask]

b11 = filter_config(bova11_df, ref)
p4  = filter_config(results,   ref)

print("Recommended config: 25delta/dte21/pt50%/OFF/mid")
print(f"{'Market':<10} {'Period':<10} {'Sharpe':>10} {'Return':>10} {'MDD':>10} {'n_trades':>10}")
print("-" * 62)
for mkt, rows in [("BOVA11", b11), ("PETR4", p4)]:
    for _, r in rows.iterrows():
        print(f"  {mkt:<8} {r.get('period_label','?'):<10} {r['sharpe']:10.3f} "
              f"{r['total_return']:10.4f} {r['max_drawdown']:10.4f} {int(r['n_trades']):10}")\
"""

cells = [
    md_cell(
        "# B3 v7 — PETR4 Grid Search\n\n"
        "Same grid spec as BOVA11 v7 (Plan 015, Phase 4).\n\n"
        "**Pilot results (18 backtests, 3 configs x 3 modes x 2 periods):**\n"
        "- 25Δ/dte21/pt50%/OFF: holdout mid=1.211, mid+1tick=2.377\n"
        "- 20Δ/dte21/pt50%/rv:80: holdout mid=0.729, mid+1tick=2.401\n"
        "- 16Δ/dte21/pt50%/rv:70: holdout mid=0.877, mid+1tick=3.908\n\n"
        "**Decision gate PASSED:** mid holdout median Sharpe = 0.877 > 0 → full grid approved.\n\n"
        "VRP exists in PETR4. Mid execution required (bid_ask holdout median: -0.835).\n\n"
        "**PETR4-specific considerations:**\n"
        "- Single stock (not ETF) → higher idiosyncratic vol\n"
        "- American exercise (BAW pricing enabled)\n"
        "- dividend_yield=0.0 (B3 preset) — PETR4 pays dividends; may slightly undervalue puts\n"
    ),
    md_cell("## 1. Imports"),
    code_cell(IMPORTS),
    md_cell("## 2. Grid Definition (same as BOVA11 v7)"),
    code_cell(GRID_DEF),
    md_cell("## 3. Run Configuration"),
    code_cell(RUNS_CELL),
    md_cell("## 4. Execute Grid Search"),
    code_cell(EXECUTE_CELL),
    md_cell("## Cell A — Sharpe vs Execution Mode"),
    code_cell(CELL_A),
    md_cell("## Cell B — Break-even Execution Level (PETR4 holdout)"),
    code_cell(CELL_B),
    md_cell("## Cell C — Delta x Execution Mode Heatmap (PETR4 holdout)"),
    code_cell(CELL_C),
    md_cell("## Cell D — Config Stability Rank (PETR4)\n\nSort by min(train_sharpe, holdout_sharpe)."),
    code_cell(CELL_D),
    md_cell("## Cell E — PETR4 vs BOVA11 Comparison (recommended config)"),
    code_cell(CELL_E),
]

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11.0"},
    },
    "cells": cells,
}

out_path = "research/2026-05-15 - B3 - v7 PETR4 grid.ipynb"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print(f"Notebook written: {out_path}")
print(f"Cells: {len(cells)}")
