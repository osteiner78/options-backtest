# Plan 022 — Entry Cooldown Sensitivity Analysis

**Date:** 2026-05-18 | **Target:** Coding agent | **Branch:** b3-backtest

---

## Context

The v7 definitive research grid fixed `entry_cooldown_days=3` (PARAMS default) across all 5,376 backtests. It was never treated as a grid dimension. Live testing revealed that the recommended config (25Δ/dte21/pt50%/manage14/OFF/mid/laddering) runs at 8–20% average BPR utilization against a 30% cap — meaning ~40–70% of available margin is idle. The strategy is profitable and capital could be deployed more efficiently by reducing the entry cooldown.

Empirically confirmed trade-off:

| Cooldown | Trades | IR (holdout 2023–2025) |
|----------|--------|------------------------|
| 3 days   | 134    | 1.36                   |
| 1 day    | 266    | 1.12                   |

`cooldown=2` and the interaction with `dte_max ∈ {30, 45}` have never been tested.

**Research question:** Is there a `(cooldown, dte_max)` combination that achieves materially higher BPR utilization (target: avg ≥ 15%) while preserving holdout IR ≥ 1.0?

---

## Grid Definition

### Fixed base config (recommended parameters from the definitive report)

| Parameter | Value | Note |
|-----------|-------|------|
| `target_delta` | 0.25 | |
| `profit_target_pct` | 0.50 | |
| `manage_at_dte` | 14 | Valid for all dte_max: 14 < dte_min for dte_max ∈ {21, 30, 45} |
| `vix_filter` | OFF | |
| `stop_loss_pct` | 2.0 | |
| `execution_mode` | mid | |
| `portfolio_mode` | laddering | |
| `market` | bova11 | |

### Sensitivity dimensions

| Dimension | Values |
|-----------|--------|
| `entry_cooldown_days` | 1, 2, 3, 5, 7 |
| `dte_max` | 21, 30, 45 |

### Periods

| Label | Start | End |
|-------|-------|-----|
| train | 2018-01-02 | 2022-12-30 |
| holdout | 2023-01-02 | 2025-11-30 |

**Total: 5 × 3 × 2 = 30 backtests**

### DTE_MIN_BY_DTE_MAX mapping (from `grid_search.py`, must be applied)

| dte_max | dte_min |
|---------|---------|
| 21 | 15 |
| 30 | 20 |
| 45 | 30 |

---

## Phase 1: Script — Run the Sensitivity Grid

Create `scripts/run_cooldown_sensitivity.py`. The script mirrors the structure of `run_v7_grid.py` but with a much smaller grid.

### Step 1.1 — Script structure

```python
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
    apply_market_preset(params, "bova11")  # sets put_slope, call_slope, tick_size, calendar, etc.
    params.update(BASE)
    params["start_date"]          = start
    params["end_date"]            = end
    params["entry_cooldown_days"] = cooldown
    params["dte_max"]             = dte_max
    params["dte_min"]             = DTE_MIN_BY_DTE_MAX[dte_max]

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
            "avg_bpr_util":        metrics.get("avg_bpr_util"),   # as % (0–100)
            "peak_bpr_util":       metrics.get("peak_bpr_util"),  # as % (0–100)
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
        if hasattr(engine, "close"):
            engine.close()

df  = pd.DataFrame(rows)
out = ROOT / "data" / "B3" / "v7_cooldown_sensitivity.parquet"
df.to_parquet(out, index=False)
print(f"\nSaved {len(df)} rows to {out}")
```

### Step 1.2 — Verify BPR metrics are available

Check that `avg_bpr_util` and `peak_bpr_util` are returned by `compute_portfolio_metrics` in `src/straddle/metrics.py`. If they are stored as fractions (0–1) rather than percentages (0–100), multiply by 100 in the script before saving.

### Step 1.3 — Run the script

```bash
python scripts/run_cooldown_sensitivity.py
```

Expected runtime: < 5 minutes (30 backtests, laddering mode, B3 market data).  
Verify: output parquet has 30 rows, zero error rows.

---

## Phase 2: Analysis Notebook

Create `research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb`. The notebook is self-contained and answers the capital utilization question.

### Step 2.1 — Load data

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT      = ...  # same as other notebooks
df        = pd.read_parquet(ROOT / "data" / "B3" / "v7_cooldown_sensitivity.parquet")
hold      = df[df["period_label"] == "holdout"].copy()
train     = df[df["period_label"] == "train"].copy()

COOLDOWNS = [1, 2, 3, 5, 7]
DTE_MAXES = [21, 30, 45]
COLORS    = {21: "#4ec9b0", 30: "#dcdcaa", 45: "#ce9178"}
```

### Step 2.2 — Cell A: IR vs `entry_cooldown_days` (primary result)

Line chart, holdout only. One line per `dte_max`.  
- x-axis: `entry_cooldown_days`  
- y-axis: IR (information ratio)  
- Vertical dashed line at `cooldown=3` (v7 research baseline)  
- Horizontal dashed line at `IR=1.0` (deployment threshold)

Also print a stability table:

| dte_max | cooldown | IR_train | IR_holdout | min(IR_train, IR_holdout) |
|---------|----------|----------|------------|---------------------------|

### Step 2.3 — Cell B: n_trades vs `entry_cooldown_days`

Line chart, holdout. One line per `dte_max`.  
Shows how trade frequency scales with cooldown and DTE window.  
Calibration question: at what cooldown does `dte30` reach the same trade count as `dte21/cooldown=3`?

### Step 2.4 — Cell C: avg_bpr_util vs `entry_cooldown_days`

Line chart, holdout. One line per `dte_max`.  
- y-axis: average BPR utilization (%)  
- Horizontal dashed lines at 10%, 15%, 20%, 30%  

This is the capital efficiency chart — the primary motivation for the analysis.

### Step 2.5 — Cell D: IR–BPR Frontier *(key decision chart)*

Scatter plot, holdout. Each point = one `(cooldown, dte_max)` combo.  
- x-axis: `avg_bpr_util` (%)  
- y-axis: IR  
- Label each point as `dte{X}/cd{Y}`  
- Draw a Pareto frontier line (highest IR for each BPR utilization level)

This chart directly answers: *which config achieves the best risk-adjusted return per unit of capital deployed?*

### Step 2.6 — Cell E: max_drawdown vs `entry_cooldown_days`

Line chart, holdout. One line per `dte_max`.  
Tests hypothesis H4: does higher concurrency increase tail risk?  
Expected: modest increase in `max_drawdown` as cooldown decreases.

### Step 2.7 — Cell F: avg_positions vs `entry_cooldown_days`

Shows average and peak concurrent open positions vs cooldown.  
Reveals when the BPR cap starts to bind (`avg_positions × BPR_per_position` approaches 30%).

### Step 2.8 — Cell G: Train vs holdout stability

For each `(cooldown, dte_max)`, scatter `IR_train` vs `IR_holdout`.  
Identifies whether lower cooldowns show more overfitting (high train / low holdout divergence).

### Step 2.9 — Summary table

Holdout results sorted by IR descending:

| rank | dte_max | cooldown | n_trades | IR | avg_bpr_util | max_dd | calmar |
|------|---------|----------|----------|----|--------------|--------|--------|

---

## Phase 3: Add Section to Definitive Research Notebook

Append section **"11. Entry Cooldown Sensitivity"** to  
`research/2026-05-15 - B3 - definitive research report.ipynb`.

### Section contents

1. **Motivation** (1 paragraph): why cooldown was fixed at 3 in v7 and why capital efficiency requires studying it
2. **Grid definition** (table: cooldown values × dte_max × fixed params)
3. **Cell A** (IR vs cooldown) — re-run inline
4. **Cell D** (IR–BPR frontier) — re-run inline
5. **Conclusion paragraph**: recommended cooldown for deployment, trade-off statement
6. **Updated recommendation table** (fill `?` cells from actual results):

| Config | Cooldown | IR holdout | Avg BPR util | Notes |
|--------|----------|------------|--------------|-------|
| 25Δ/dte21/pt50%/mid (v7 baseline) | 3 | 1.33 | ~10% | Research default |
| 25Δ/dte21/pt50%/mid (efficient) | ? | ?.?? | ~??% | From frontier |
| 25Δ/dte30/pt50%/mid (efficient) | ? | ?.?? | ~??% | From frontier |

---

## Key Hypotheses to Test

| # | Hypothesis |
|---|-----------|
| H1 | IR is maximized at `cooldown=3` for `dte_max=21` — lower cooldowns degrade IR by amplifying daily P&L variance through overlapping positions |
| H2 | For `dte_max=30` or `45`, a lower cooldown (1–2) achieves better BPR utilization with less IR degradation, because longer-dated positions spread decay across more calendar days |
| H3 | The BPR cap (30%) starts to bind at some `(cooldown, dte_max)` — `avg_positions × BPR_per_position` exceeds 30% — revealing a natural capacity ceiling |
| H4 | `max_drawdown` is relatively insensitive to cooldown: positions opened close together hit the same market events (correlated losses cancel the concurrency benefit) |

---

## Definition of Done

- [ ] `scripts/run_cooldown_sensitivity.py` created and executes without errors
- [ ] `data/B3/v7_cooldown_sensitivity.parquet` saved — 30 rows, 0 error rows
- [ ] `avg_bpr_util` and `peak_bpr_util` verified in parquet (not all zeros/NaN)
- [ ] `research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb` created, all cells executed
- [ ] Cell D (IR–BPR frontier) identifies the Pareto-optimal `(cooldown, dte_max)` combo
- [ ] Section 11 appended to definitive report notebook with updated recommendation table
- [ ] All existing 129 tests still pass (no engine changes required)

---

## Files

| File | Action |
|------|--------|
| `scripts/run_cooldown_sensitivity.py` | New — 30-backtest grid runner |
| `data/B3/v7_cooldown_sensitivity.parquet` | New — grid results |
| `research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb` | New — analysis notebook |
| `research/2026-05-15 - B3 - definitive research report.ipynb` | Edit — append Section 11 |

---

## Deviations Allowed

- If `avg_bpr_util` is not available from `compute_portfolio_metrics`, derive it from the `bpr_curve` output: `avg_bpr_util = bpr_curve.mean() / initial_balance × 100`.
- If runtime exceeds 10 minutes, check for missing DB data causing repeated synthetic fallbacks; log `entry_db_pct` per run to diagnose.
- Phase 3 (notebook edit) may be skipped if Section 11 would make the definitive report unwieldy — keep it as a standalone notebook and add a cross-reference instead.
- If H2 is confirmed (`dte30/cooldown=1` or `2` dominates the frontier), add a follow-up note recommending a targeted deep-dive: 25Δ/dte30 × `cooldown=[1,2,3]` × `manage_at_dte=[7,14]` (12 backtests) to find the optimal management threshold for the new winner.
