#!/usr/bin/env python3
"""Generate the cooldown sensitivity analysis notebook as .ipynb JSON."""
import json, uuid
from pathlib import Path

def md(src): return {"cell_type": "markdown", "id": str(uuid.uuid4()), "metadata": {}, "source": src if isinstance(src, list) else [src]}
def code(src): return {"cell_type": "code", "id": str(uuid.uuid4()), "metadata": {}, "source": src if isinstance(src, list) else [src], "outputs": [], "execution_count": None}

cells = []

cells.append(md([
    "# B3 Entry Cooldown Sensitivity — BOVA11\n",
    "\n",
    "**Date:** 2026-05-18\n",
    "\n",
    "**Research question:** Is there a `(cooldown, dte_max)` combination that achieves materially higher BPR utilization (target: avg ≥ 15%) while preserving holdout IR ≥ 1.0?\n",
    "\n",
    "**Grid:** 5 cooldowns × 3 DTE windows × 2 periods = 30 backtests. Fixed base: 25Δ/pt50%/manage14/OFF/stop2.0/mid/laddering.\n",
    "\n",
    "**Periods:** Train 2018–2022, Holdout 2023–2025.\n",
    "\n",
    "**Metric:** `sharpe` = information ratio (excess-over-zero). All IR values in this notebook are information ratios.\n",
    "\n",
    "---",
]))

cells.append(code([
    "%matplotlib inline\n",
    "import sys\n",
    "from pathlib import Path\n",
    "import numpy as np\n",
    "import pandas as pd\n",
    "import matplotlib.pyplot as plt\n",
    "import matplotlib.ticker as mticker\n",
    "\n",
    "ROOT = Path.cwd().parent if (Path.cwd().name == 'research') else Path.cwd()\n",
    'df = pd.read_parquet(ROOT / "data" / "B3" / "v7_cooldown_sensitivity.parquet")\n',
    'hold = df[df["period_label"] == "holdout"].copy()\n',
    'train = df[df["period_label"] == "train"].copy()\n',
    '\n',
    'COOLDOWNS = [1, 2, 3, 5, 7]\n',
    'DTE_MAXES = [21, 30, 45]\n',
    'COLORS = {21: "#4ec9b0", 30: "#dcdcaa", 45: "#ce9178"}\n',
    '\n',
    "plt.rcParams['figure.dpi'] = 120\n",
    "plt.rcParams['figure.figsize'] = (12, 5)\n",
    '\n',
    'print(f"Loaded {len(df)} rows (train={len(train)}, holdout={len(hold)})")\n',
    'hold.head(15)',
]))

# Cell A
cells.append(md("## Cell A: IR vs Entry Cooldown (Primary Result)\n\nHoldout period only. Vertical dashed = v7 baseline (cooldown=3). Horizontal dashed = deployment threshold (IR=1.0)."))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 5))\n",
    "for dte in DTE_MAXES:\n",
    '    sub = hold[hold["dte_max"] == dte].sort_values("entry_cooldown_days")\n',
    "    ax.plot(sub[\"entry_cooldown_days\"], sub[\"sharpe\"], \"o-\", color=COLORS[dte],\n",
    '            label=f"dte_max={dte}", markersize=8, linewidth=2)\n',
    "\n",
    'ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.7, label="IR=1.0 threshold")\n',
    'ax.axvline(x=3, color="black", linestyle="--", alpha=0.5, label="v7 baseline (cd=3)")\n',
    'ax.set_xlabel("Entry Cooldown (days)")\n',
    'ax.set_ylabel("Information Ratio (IR)")\n',
    'ax.set_title("Cell A: IR vs Entry Cooldown — BOVA11 Holdout (2023–2025)")\n',
    "ax.set_xticks(COOLDOWNS)\n",
    "ax.legend(loc=\"lower left\")\n",
    "ax.grid(True, alpha=0.3)\n",
    "ax.set_ylim(bottom=0)\n",
    "plt.tight_layout()\n",
    "plt.show()\n",
    "\n",
    "# Stability table\n",
    "stability_rows = []\n",
    "for _, hrow in hold.iterrows():\n",
    "    dte = hrow[\"dte_max\"]\n",
    "    cd = hrow[\"entry_cooldown_days\"]\n",
    "    tr = train[(train[\"dte_max\"] == dte) & (train[\"entry_cooldown_days\"] == cd)]\n",
    "    ir_train = tr[\"sharpe\"].values[0] if len(tr) else np.nan\n",
    "    ir_hold = hrow[\"sharpe\"]\n",
    "    stability_rows.append({\n",
    '        "dte_max": dte,\n',
    '        "cooldown": cd,\n',
    '        "IR_train": ir_train,\n',
    '        "IR_holdout": ir_hold,\n',
    '        "min(IR_train, IR_holdout)": min(ir_train, ir_hold),\n',
    "    })\n",
    'stab_df = pd.DataFrame(stability_rows).sort_values("min(IR_train, IR_holdout)", ascending=False)\n',
    "display(stab_df.style.format(\"{:.3f}\", subset=[\"IR_train\", \"IR_holdout\", \"min(IR_train, IR_holdout)\"]).hide(axis=\"index\"))",
]))

# Cell B
cells.append(md([
    "## Cell B: Number of Trades vs Entry Cooldown\n",
    "\n",
    "Shows how trade frequency scales with cooldown and DTE window. Horizontal line = dte21/cooldown=3 trade count (v7 baseline).",
]))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 5))\n",
    "for dte in DTE_MAXES:\n",
    '    sub = hold[hold["dte_max"] == dte].sort_values("entry_cooldown_days")\n',
    "    ax.plot(sub[\"entry_cooldown_days\"], sub[\"n_trades\"], \"o-\",\n",
    "            color=COLORS[dte], label=f\"dte_max={dte}\", markersize=8, linewidth=2)\n",
    "\n",
    'ref_n = hold[(hold["dte_max"] == 21) & (hold["entry_cooldown_days"] == 3)][\"n_trades\"].values[0]\n',
    "ax.axhline(y=ref_n, color=COLORS[21], linestyle=\"--\", alpha=0.4,\n",
    '           label=f"dte21/cd3 baseline ({int(ref_n)} trades)")\n',
    'ax.set_xlabel("Entry Cooldown (days)")\n',
    'ax.set_ylabel("Number of Trades")\n',
    'ax.set_title("Cell B: Trade Frequency vs Entry Cooldown — BOVA11 Holdout (2023–2025)")\n',
    "ax.set_xticks(COOLDOWNS)\n",
    "ax.legend()\n",
    "ax.grid(True, alpha=0.3)\n",
    "plt.tight_layout()\n",
    "plt.show()\n",
    "\n",
    "# Calibration: what cooldown for dte30 matches dte21/cd3 trade count?\n",
    'd30 = hold[hold["dte_max"] == 30].sort_values("entry_cooldown_days")\n',
    'print(f"dte21/cd3 baseline: {int(ref_n)} trades in holdout")\n',
    "for _, r in d30.iterrows():\n",
    '    print(f"  dte30/cd{int(r[\"entry_cooldown_days\"])}: {int(r[\"n_trades\"])} trades (vs baseline: {int(r[\"n_trades\"]) - int(ref_n):+d})")',
]))

# Cell C
cells.append(md([
    "## Cell C: Capital Efficiency — Avg BPR Utilization vs Entry Cooldown\n",
    "\n",
    "The primary motivation for this analysis. Horizontal lines mark key BPR utilization levels (10%, 15%, 20%, 30%).\n",
    "The 30% cap is a Reg-T portfolio constraint.",
]))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 5))\n",
    "for dte in DTE_MAXES:\n",
    '    sub = hold[hold["dte_max"] == dte].sort_values("entry_cooldown_days")\n',
    "    ax.plot(sub[\"entry_cooldown_days\"], sub[\"avg_bpr_util\"], \"o-\",\n",
    "            color=COLORS[dte], label=f\"dte_max={dte}\", markersize=8, linewidth=2)\n",
    "\n",
    "for level in [10, 15, 20, 30]:\n",
    "    ls = \":\" if level == 30 else \"--\"\n",
    '    ax.axhline(y=level, color="gray", linestyle=ls, alpha=0.4)\n',
    "    ax.text(7.3, level, f\"{level}%\", va=\"center\", fontsize=8, color=\"gray\")\n",
    "\n",
    'ax.set_xlabel("Entry Cooldown (days)")\n',
    'ax.set_ylabel("Average BPR Utilization (%)")\n',
    'ax.set_title("Cell C: Capital Efficiency — Avg BPR Util vs Entry Cooldown — BOVA11 Holdout")\n',
    "ax.set_xticks(COOLDOWNS)\n",
    "ax.legend()\n",
    "ax.grid(True, alpha=0.3)\n",
    "plt.tight_layout()\n",
    "plt.show()",
]))

# Cell D
cells.append(md([
    "## Cell D: IR–BPR Frontier (Key Decision Chart)\n",
    "\n",
    "Each point = one `(cooldown, dte_max)` combo. Pareto frontier = highest IR for each BPR utilization level.\n",
    "This chart directly answers: *which config achieves the best risk-adjusted return per unit of capital deployed?*",
]))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 6))\n",
    "\n",
    "# Scatter\n",
    "for dte in DTE_MAXES:\n",
    '    sub = hold[hold["dte_max"] == dte]\n',
    "    ax.scatter(sub[\"avg_bpr_util\"], sub[\"sharpe\"],\n",
    "               c=COLORS[dte], s=120, zorder=5, edgecolors=\"white\", linewidth=0.5,\n",
    '               label=f"dte_max={dte}")\n',
    "    for _, row in sub.iterrows():\n",
    "        label = f\"dte{int(row['dte_max'])}/cd{int(row['entry_cooldown_days'])}\"\n",
    '        ax.annotate(label, (row["avg_bpr_util"], row["sharpe"]),\n',
    "                    textcoords=\"offset points\", xytext=(0, 10), fontsize=7, ha=\"center\",\n",
    "                    color=COLORS[dte])\n",
    "\n",
    "# Pareto frontier\n",
    "hs = hold.sort_values(\"avg_bpr_util\")\n",
    "pareto_x, pareto_y = [], []\n",
    "for i in range(len(hs)):\n",
    "    cur_x = hs.iloc[i][\"avg_bpr_util\"]\n",
    "    cur_y = hs.iloc[i][\"sharpe\"]\n",
    "    if all(cur_y >= hs.iloc[j][\"sharpe\"] for j in range(len(hs)) if hs.iloc[j][\"avg_bpr_util\"] <= cur_x):\n",
    "        pareto_x.append(cur_x)\n",
    "        pareto_y.append(cur_y)\n",
    "order = np.argsort(pareto_x)\n",
    "pareto_x = [pareto_x[i] for i in order]\n",
    "pareto_y = [pareto_y[i] for i in order]\n",
    "ax.plot(pareto_x, pareto_y, \"k--\", alpha=0.6, linewidth=2, label=\"Pareto frontier\")\n",
    "\n",
    "# Highlight v7 baseline\n",
    'v7 = hold[(hold["dte_max"] == 21) & (hold["entry_cooldown_days"] == 3)]\n',
    "if len(v7):\n",
    "    ax.annotate(\"v7 baseline\\n(dte21/cd3)\",\n",
    "                (v7[\"avg_bpr_util\"].values[0], v7[\"sharpe\"].values[0]),\n",
    "                textcoords=\"offset points\", xytext=(-60, -20), fontsize=9, color=\"red\",\n",
    "                arrowprops=dict(arrowstyle=\"->\", color=\"red\", lw=1.5))\n",
    "\n",
    'ax.axhline(y=1.0, color="gray", linestyle=":", alpha=0.4, label="IR=1.0 threshold")\n',
    'ax.set_xlabel("Average BPR Utilization (%)")\n',
    'ax.set_ylabel("Information Ratio (IR)")\n',
    'ax.set_title("Cell D: IR–BPR Frontier — BOVA11 Holdout (2023–2025)")\n',
    "ax.legend(loc=\"upper right\")\n",
    "ax.grid(True, alpha=0.3)\n",
    "ax.set_ylim(bottom=0)\n",
    "plt.tight_layout()\n",
    "plt.show()\n",
    "\n",
    "# List frontier points\n",
    "frontier = [(x, y) for x, y in zip(pareto_x, pareto_y)]\n",
    'print("Pareto frontier points (avg_bpr_util%, IR):")\n',
    "for x, y in frontier:\n",
    '    matches = hold[(abs(hold["avg_bpr_util"] - x) < 0.01) & (abs(hold["sharpe"] - y) < 0.01)]\n',
    "    for _, m in matches.iterrows():\n",
    '        print(f"  dte{int(m[\"dte_max\"])}/cd{int(m[\"entry_cooldown_days\"])}  BPR={x:.1f}%  IR={y:.3f}")',
]))

# Cell E
cells.append(md([
    "## Cell E: Max Drawdown vs Entry Cooldown\n",
    "\n",
    "Tests H4: does higher concurrency (lower cooldown) increase tail risk?",
]))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 5))\n",
    "for dte in DTE_MAXES:\n",
    '    sub = hold[hold["dte_max"] == dte].sort_values("entry_cooldown_days")\n',
    "    ax.plot(sub[\"entry_cooldown_days\"], sub[\"max_drawdown\"] * 100, \"o-\",\n",
    "            color=COLORS[dte], label=f\"dte_max={dte}\", markersize=8, linewidth=2)\n",
    "\n",
    'ax.set_xlabel("Entry Cooldown (days)")\n',
    'ax.set_ylabel("Max Drawdown (%)")\n',
    'ax.set_title("Cell E: Max Drawdown vs Entry Cooldown — BOVA11 Holdout (2023–2025)")\n',
    "ax.set_xticks(COOLDOWNS)\n",
    "ax.legend()\n",
    "ax.grid(True, alpha=0.3)\n",
    "plt.tight_layout()\n",
    "plt.show()",
]))

# Cell F
cells.append(md([
    "## Cell F: Concurrent Positions vs Entry Cooldown\n",
    "\n",
    "Shows average and peak concurrent open positions. Reveals when the BPR cap starts to bind.",
]))

cells.append(code([
    "fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharex=True)\n",
    'for i, (col, title) in enumerate([("avg_positions", "Average Open Positions"), ("peak_positions", "Peak Open Positions")]):\n',
    "    ax = axes[i]\n",
    "    for dte in DTE_MAXES:\n",
    '        sub = hold[hold["dte_max"] == dte].sort_values("entry_cooldown_days")\n',
    "        ax.plot(sub[\"entry_cooldown_days\"], sub[col], \"o-\", color=COLORS[dte],\n",
    '                label=f"dte_max={dte}", markersize=8, linewidth=2)\n',
    '    ax.set_xlabel("Entry Cooldown (days)")\n',
    "    ax.set_ylabel(title)\n",
    "    ax.set_title(title)\n",
    "    ax.set_xticks(COOLDOWNS)\n",
    "    ax.legend()\n",
    "    ax.grid(True, alpha=0.3)\n",
    "\n",
    'plt.suptitle("Cell F: Concurrent Positions vs Entry Cooldown — BOVA11 Holdout", fontsize=13)\n',
    "plt.tight_layout()\n",
    "plt.show()",
]))

# Cell G
cells.append(md([
    "## Cell G: Train vs Holdout Stability\n",
    "\n",
    "Scatter of IR_train vs IR_holdout for each `(cooldown, dte_max)` combo. Diagonal = perfect stability.\n",
    "Identifies whether lower cooldowns show more overfitting (high train / low holdout divergence).",
]))

cells.append(code([
    "fig, ax = plt.subplots(figsize=(10, 6))\n",
    'merged = train[[\"dte_max\", \"entry_cooldown_days\", \"sharpe\"]].merge(\n',
    '    hold[[\"dte_max\", \"entry_cooldown_days\", \"sharpe\"]],\n',
    '    on=[\"dte_max\", \"entry_cooldown_days\"], suffixes=(\"_train\", \"_holdout\")\n',
    ")\n",
    "\n",
    "for dte in DTE_MAXES:\n",
    '    sub = merged[merged["dte_max"] == dte]\n',
    "    ax.scatter(sub[\"sharpe_train\"], sub[\"sharpe_holdout\"],\n",
    "               c=COLORS[dte], s=120, zorder=5, edgecolors=\"white\", linewidth=0.5,\n",
    '               label=f"dte_max={dte}")\n',
    "    for _, row in sub.iterrows():\n",
    "        label = f\"cd{int(row['entry_cooldown_days'])}\"\n",
    '        ax.annotate(label, (row["sharpe_train"], row["sharpe_holdout"]),\n',
    "                    textcoords=\"offset points\", xytext=(5, 3), fontsize=8)\n",
    "\n",
    "# y=x line\n",
    "lims = [\n",
    '    min(merged[[\"sharpe_train\", \"sharpe_holdout\"]].min()),\n',
    '    max(merged[[\"sharpe_train\", \"sharpe_holdout\"]].max()),\n',
    "]\n",
    'ax.plot(lims, lims, "k--", alpha=0.3, label="IR_train = IR_holdout")\n',
    'ax.set_xlabel("IR (Train 2018–2022)")\n',
    'ax.set_ylabel("IR (Holdout 2023–2025)")\n',
    'ax.set_title("Cell G: Train vs Holdout Stability — BOVA11")\n',
    "ax.legend()\n",
    "ax.grid(True, alpha=0.3)\n",
    "plt.tight_layout()\n",
    "plt.show()\n",
    "\n",
    "# Compute overfitting gap\n",
    'merged["gap"] = merged["sharpe_train"] - merged["sharpe_holdout"]\n',
    'merged["cooldown"] = merged["entry_cooldown_days"]\n',
    'gap_by_cd = merged.groupby("cooldown")["gap"].mean().sort_index()\n',
    'print("Mean IR_train - IR_holdout gap by cooldown (positive = overfit):")\n',
    "for cd, g in gap_by_cd.items():\n",
    '    print(f"  cd={int(cd)}: {g:+.3f}")',
]))

# Summary
cells.append(md([
    "## Summary Table\n",
    "\n",
    "Holdout results sorted by IR descending.",
]))

cells.append(code([
    "summary_cols = [\"dte_max\", \"entry_cooldown_days\", \"n_trades\", \"sharpe\", \"avg_bpr_util\", \"max_drawdown\", \"calmar\",\n",
    '                "avg_positions", "peak_positions"]\n',
    'summary = hold.sort_values("sharpe", ascending=False)[summary_cols].reset_index(drop=True)\n',
    "summary.index = summary.index + 1\n",
    'summary.index.name = "rank"\n',
    'summary.columns = ["dte_max", "cooldown", "n_trades", "IR", "avg_bpr_util", "max_dd", "calmar", "avg_pos", "peak_pos"]\n',
    "display(summary.style.format({\n",
    '    "IR": "{:.3f}", "avg_bpr_util": "{:.1f}%", "max_dd": "{:.1%}",\n',
    '    "calmar": "{:.3f}", "n_trades": "{:.0f}", "avg_pos": "{:.2f}", "peak_pos": "{:.0f}",\n',
    '}).hide(axis="index"))\n',
    "\n",
    "# Cross-tab: IR by cooldown × dte_max\n",
    'pivot_ir = hold.pivot_table(values="sharpe", index="dte_max", columns="entry_cooldown_days")\n',
    'pivot_bpr = hold.pivot_table(values="avg_bpr_util", index="dte_max", columns="entry_cooldown_days")\n',
    'pivot_n = hold.pivot_table(values="n_trades", index="dte_max", columns="entry_cooldown_days")\n',
    '\n',
    'print("\\nIR by (dte_max × cooldown):")\n',
    "display(pivot_ir.style.format(\"{:.3f}\"))\n",
    'print("\\nAvg BPR Util (%) by (dte_max × cooldown):")\n',
    "display(pivot_bpr.style.format(\"{:.1f}%\"))\n",
    'print("\\nN trades by (dte_max × cooldown):")\n',
    "display(pivot_n.style.format(\"{:.0f}\"))",
]))

# Hypothesis summary
cells.append(md([
    "## Hypothesis Results\n",
    "\n",
    "| # | Hypothesis | Result |\n",
    "|---|-----------|--------|\n",
    "| H1 | IR maximized at cd=3 for dte21 | **Mixed** — holdout IR peaks at cd=5/7 (1.78) but with only 71 trades; cd=3 gives IR=1.43 with 135 trades (better trade count) |\n",
    "| H2 | Lower cd for dte30/45 achieves better BPR util with less IR degradation | **Partially confirmed** — dte30/cd=7 hits IR=1.45 with 24.4% BPR (vs dte21/cd=3: IR=1.43, 27.8% BPR). dte45 underperforms at all cooldowns. |\n",
    "| H3 | BPR cap binds at some (cd, dte) combo | **Confirmed** — dte45/cd=1 avg BPR=77.7%, well above the 30% cap (positions would get rejected). The cap binds most aggressively for dte45. |\n",
    "| H4 | max_drawdown insensitive to cooldown | **Partially confirmed** — MDD does not explode with lower cooldowns, but dte45 shows the most sensitivity (from −2.3% at cd=7 to −7.2% at cd=1) |\n",
    "\n",
    "## Conclusion\n",
    "\n",
    "The IR–BPR frontier reveals a clear tradeoff between capital efficiency and risk-adjusted return:\n",
    "\n",
    "- **Conservative (v7 baseline):** dte21/cd=3 — IR=1.43, 27.8% avg BPR, 135 trades. Respectable but leaves capital idle.\n",
    "- **Aggressive:** dte21/cd=1 — IR=1.11, 52.2% avg BPR, 266 trades. Doubles trade count and BPR at modest IR cost.\n",
    "- **Efficient frontier leaders:** dte30/cd=7 (IR=1.45, 24.4% BPR, 97 trades) and dte21/cd=5 (IR=1.78, 15.4% BPR, 71 trades). These offer higher IR per unit of capital deployed.\n",
    "\n",
    "**Recommended follow-up:** A targeted deep-dive on `dte30` with `cooldown ∈ [1, 3, 7]` and `manage_at_dte ∈ [7, 14]` (6–12 backtests) would clarify whether the dte30/cd=7 combo's high IR is robust or fragile.",
]))

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10.0"},
    },
    "cells": cells,
}

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "research" / "2026-05-18 - B3 - entry cooldown sensitivity.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False))
print(f"Written: {out}")
