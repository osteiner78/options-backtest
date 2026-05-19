# Plan 023 — DTE30 Cooldown Deep-Dive

**Date:** 2026-05-18 | **Target:** Coding agent | **Branch:** b3-backtest

---

## Context

Plan 022 (entry cooldown sensitivity) ran 30 backtests across `cooldown ∈ {1,2,3,5,7}` × `dte_max ∈ {21,30,45}` with `manage_at_dte=14` fixed. The notebook conclusion (Section: *Hypothesis Results*) identified dte30 as the most promising frontier region and flagged two open questions:

1. **dte30/cd=7 hits IR=1.45 with 97 trades** — higher IR than the v7 baseline (dte21/cd=3: IR=1.43) but with better BPR utilization (24.4% vs 27.8%). Is this result robust across manage_at_dte values, or an artifact of the fixed manage_at_dte=14?
2. **manage_at_dte was never varied for dte30** — the v7 grid found that short DTE windows favor manage_at_dte=14, but dte30 may have a different optimum (the v7 top stability configs for dte30 used manage_at_dte=7, not 14).
3. **dte21/cd=5 and cd=7 produce identical results** (IR=1.779, 71 trades) — the B3 expiration calendar saturates at ~71 entries for dte21 in the 2023–2025 holdout window. These high-IR configs have too few trades to be statistically reliable. dte30 avoids this saturation (cd=7 → 97 trades, cd=5 → 119 trades).

The notebook recommended: *"A targeted deep-dive on dte30 with cooldown ∈ [1, 3, 7] and manage_at_dte ∈ [7, 14] to clarify whether the dte30/cd=7 combo's high IR is robust or fragile."*

This plan formalises and extends that recommendation.

---

## Grid Definition

### Fixed base config

| Parameter | Value | Note |
|-----------|-------|------|
| `target_delta` | 0.25 | Recommended from v7 |
| `dte_max` | 30 | Focus market |
| `dte_min` | 20 | From `DTE_MIN_BY_DTE_MAX[30]` |
| `vix_filter` | OFF | Consistent with recommendation |
| `stop_loss_pct` | 2.0 | Consistent with v7 |
| `execution_mode` | mid | Required |
| `portfolio_mode` | laddering | Required |
| `market` | bova11 | |

### Sensitivity dimensions

| Dimension | Values | Rationale |
|-----------|--------|-----------|
| `entry_cooldown_days` | 1, 2, 3, 5, 7 | Full range for continuity with Plan 022 |
| `manage_at_dte` | 5, 7, 14 | All valid for dte30 (must be < dte_min=20) |
| `profit_target_pct` | 0.25, 0.50 | v7 found pt=25% dominant for dte30 in 12Δ configs |

### Periods

| Label | Start | End |
|-------|-------|-----|
| train | 2018-01-02 | 2022-12-30 |
| holdout | 2023-01-02 | 2025-11-30 |

**Primary grid: 5 × 3 × 2 × 2 = 60 backtests**

### Optional — Period Robustness (Phase 3)

For the top 3 configs from Phase 2, run 3 data-rich rolling windows × 2 periods = 6 additional backtests per config = **18 backtests**.

| Window | Start | End |
|--------|-------|-----|
| W1 | 2018-01-02 | 2020-12-31 |
| W2 | 2020-01-02 | 2022-12-30 |
| W3 | 2022-01-03 | 2024-12-31 |

---

## Phase 1: Script — Run the Deep-Dive Grid

Create `scripts/run_dte30_deep_dive.py`. Extends `run_cooldown_sensitivity.py` with `manage_at_dte` and `profit_target_pct` as additional dimensions.

### Step 1.1 — Script structure

```python
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

COOLDOWNS     = [1, 2, 3, 5, 7]
MANAGE_DTES   = [5, 7, 14]
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
    apply_market_preset(params, "bova11")
    params.update(BASE)
    params["start_date"]          = start
    params["end_date"]            = end
    params["entry_cooldown_days"] = cooldown
    params["manage_at_dte"]       = manage_dte
    params["profit_target_pct"]   = pt_pct

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
        if hasattr(engine, "close"):
            engine.close()

df  = pd.DataFrame(rows)
out = ROOT / "data" / "B3" / "v7_dte30_deep_dive.parquet"
df.to_parquet(out, index=False)
print(f"\nSaved {len(df)} rows to {out}")
```

### Step 1.2 — Run the script

```bash
python scripts/run_dte30_deep_dive.py
```

Expected runtime: < 15 minutes (60 backtests, dte30 positions run longer than dte21).  
Verify: 60 rows, 0 error rows.

---

## Phase 2: Analysis Notebook

Create `research/2026-05-18 - B3 - dte30 deep dive.ipynb`.

### Step 2.1 — Load data and define dimensions

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT      = ...
df        = pd.read_parquet(ROOT / "data" / "B3" / "v7_dte30_deep_dive.parquet")
hold      = df[df["period_label"] == "holdout"].copy()
train     = df[df["period_label"] == "train"].copy()

COOLDOWNS  = [1, 2, 3, 5, 7]
MGMT_DTES  = [5, 7, 14]
PTS        = [0.25, 0.50]
COLORS_MGR = {5: "#f48771", 7: "#dcdcaa", 14: "#4ec9b0"}
COLORS_PT  = {0.25: "#4ec9b0", 0.50: "#dcdcaa"}
```

### Step 2.2 — Cell A: IR heatmap — manage_at_dte × cooldown

Two heatmaps (one per `profit_target_pct`), holdout only.  
x-axis: `entry_cooldown_days`, y-axis: `manage_at_dte`. Cell values: IR.  
Highlight the best cell per heatmap. Reference: dte30/cd=7/mgr=14/pt=50% from Plan 022 (IR=1.45).

### Step 2.3 — Cell B: IR vs cooldown, by manage_at_dte

Line chart, holdout only, `profit_target_pct=0.50`. One line per `manage_at_dte`.  
Answers: does manage_at_dte=7 outperform manage_at_dte=14 for dte30 at any cooldown?

### Step 2.4 — Cell C: Profit target comparison

Side-by-side: median IR by `profit_target_pct` across all cooldown × manage combos.  
Confirms whether pt=25% or pt=50% is better for 25Δ/dte30.

### Step 2.5 — Cell D: Train vs holdout stability

Scatter of IR_train vs IR_holdout for all 30 holdout configs (5 cooldowns × 3 manage × 2 pt).  
Points on/above the diagonal are robust. Flag configs with large train/holdout divergence.  
Color by `manage_at_dte`.

### Step 2.6 — Cell E: IR–BPR frontier (updated)

Reproduce Cell D from Plan 022 notebook, now extended with the best dte30 configs from this run.  
Overlay the dte21 Pareto frontier from Plan 022 as a dashed reference line.  
Shows whether any dte30 config beats the dte21 frontier.

### Step 2.7 — Cell F: BPR utilization × manage_at_dte

How does `manage_at_dte` affect capital efficiency?  
Shorter manage_at_dte → positions close faster → fewer concurrent positions → lower BPR util.  
Longer manage_at_dte → positions linger → more concurrent → higher BPR util.

### Step 2.8 — Summary table

Top 10 holdout configs, sorted by `min(IR_train, IR_holdout)` (stability rank):

| rank | cooldown | manage_at_dte | pt | n_trades | IR_train | IR_holdout | min_IR | avg_bpr_util | max_dd |
|------|----------|---------------|----|----------|----------|------------|--------|--------------|--------|

---

## Phase 3: Period Robustness (conditional)

**Trigger:** Run Phase 3 if any dte30 config from Phase 2 achieves `min(IR_train, IR_holdout) > 1.20` AND `n_trades ≥ 80` in holdout.

For the top 3 configs (by stability rank), run 3 data-rich rolling windows:

| Window | Start | End | Expected DB coverage |
|--------|-------|-----|----------------------|
| W1 | 2018-01-02 | 2020-12-31 | ~65% |
| W2 | 2020-01-02 | 2022-12-30 | ~85% |
| W3 | 2022-01-03 | 2024-12-31 | ~99% |

Report: fraction of `(config × window)` pairs with IR > 0. Target: ≥ 90% (consistent with BOVA11 period robustness from the definitive report).

---

## Phase 4: Update Definitive Report

Append section **"12. DTE30 Deep-Dive"** to  
`research/2026-05-15 - B3 - definitive research report.ipynb`.

### Section contents

1. **Motivation** (1 paragraph): Plan 022 identified dte30/cd=7 as a frontier candidate; Plan 023 validates it
2. **Optimal manage_at_dte for dte30** (from Cell B/A)
3. **Profit target verdict** (from Cell C)
4. **Stability verdict** (from Cell D)
5. **Updated full recommendation table:**

| Config | Cooldown | manage_at_dte | pt | IR holdout | Avg BPR util | n_trades | Notes |
|--------|----------|---------------|----|------------|--------------|----------|-------|
| dte21/cd=3/mgr=14/pt=50% (v7) | 3 | 14 | 50% | 1.33 | ~28% | 134 | Research baseline |
| dte30/cd=?/mgr=?/pt=?% (new) | ? | ? | ?% | ?.?? | ~??% | ??? | Fill from results |

---

## Key Questions to Answer

| # | Question | Expected from Plan 022 data |
|---|----------|-----------------------------|
| Q1 | What is the optimal `manage_at_dte` for dte30/25Δ? | Likely 7 (v7 top stability configs used mgr=7 for dte30) |
| Q2 | Does pt=25% outperform pt=50% for dte30/25Δ? | Likely yes, mirroring the 12Δ/dte30 v7 finding |
| Q3 | Is dte30/cd=7/mgr=14/pt=50% (IR=1.45 in Plan 022) robust? | Check if IR_train > 1.0 as well |
| Q4 | Does any dte30 config beat dte21/cd=3 on BOTH IR and BPR utilization? | Frontier from Cell E |
| Q5 | Does the dte21 calendar saturation (cd=5 ≡ cd=7 → 71 trades) also appear for dte30? | Check if cd=5 ≡ cd=7 for dte30 |

---

## Definition of Done

- [ ] `scripts/run_dte30_deep_dive.py` created and executes without errors
- [ ] `data/B3/v7_dte30_deep_dive.parquet` saved — 60 rows, 0 error rows
- [ ] `research/2026-05-18 - B3 - dte30 deep dive.ipynb` created, all cells executed
- [ ] Cell A heatmap identifies the best `(cooldown, manage_at_dte)` combination for each profit target
- [ ] Cell D confirms or refutes robustness of dte30/cd=7
- [ ] Cell E (updated frontier) shows whether dte30 beats the dte21 Pareto frontier from Plan 022
- [ ] Phase 3 triggered or explicitly skipped with justification
- [ ] Section 12 appended to definitive report with updated recommendation table
- [ ] All existing 129 tests still pass

---

## Files

| File | Action |
|------|--------|
| `scripts/run_dte30_deep_dive.py` | New — 60-backtest grid runner |
| `data/B3/v7_dte30_deep_dive.parquet` | New — grid results |
| `research/2026-05-18 - B3 - dte30 deep dive.ipynb` | New — analysis notebook |
| `research/2026-05-15 - B3 - definitive research report.ipynb` | Edit — append Section 12 |

---

## Deviations Allowed

- If `manage_at_dte=5` is consistently worst across all cooldowns (IR < 0.8), drop it from Cell B and the summary table — note it as "below threshold" and focus discussion on mgr=7 vs mgr=14.
- If no dte30 config achieves `min(IR_train, IR_holdout) > 1.0`, Phase 3 is skipped and the conclusion is "dte21/cd=3 remains the recommendation; dte30 does not improve the frontier."
- If dte30 calendar saturation is observed (cd=5 ≡ cd=7 in trade count), collapse those rows in tables and note the B3 expiration calendar ceiling explicitly.
- Phase 4 (definitive report edit) may be skipped if the dte30 result is negative — in that case add only a brief note in Section 11 of the cooldown sensitivity report.
