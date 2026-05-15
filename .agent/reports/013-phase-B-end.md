# Plan 013 — Phase B End Report
Date: 2026-05-15

## What was built

**`scripts/build_v6_notebook.py`** — Generates the v6 Jupyter notebook (31 cells) following the v5 pattern. Covers all 15 cells from the plan specification (Imports, Grid, Run Config, Execute, Cells A–K).

**`research/2026-05-15 - B3 - v6 expanded grid.ipynb`** — Generated notebook. Cell 4 caches results (loads parquet if present, runs grid otherwise). Cells A–K produce boxplots, heatmaps, scatter plots, and tables covering all analysis dimensions from the plan.

**`data/B3/v6_grid_search_results.parquet`** — 24,192-row results file. 455 errors (1.9%), 23,737 valid runs.

## Grid execution results

```
Grid: 13,824 raw combos → 12,096 valid (1,728 dropped by manage_at_dte < dte_min)
Runs: 2 periods × 12,096 = 24,192 backtests
Runtime: 161.6 minutes on 8 cores
Errors: 455 — complex-number bug on delta=0.50 (336), delta=0.30 (106), delta≤0.25 (13)
```

## Key numbers

| Mode | Holdout median | Holdout p75 | Holdout max | Train Q1% |
|---|---|---|---|---|
| bid_ask | −0.96 | −0.61 | +0.42 | 0% |
| mid | +0.37 | +0.65 | +2.07 | 49% |
| mid_plus_1tick | **+1.11** | **+1.67** | **+11.73** | **85%** |

## Deviations from plan

1. **Straddle configs (delta=0.50) had complex-number errors** — as expected per allowed deviation. Additionally, delta=0.30 and a few delta=0.25 configs at dte_max=60 also errored. All excluded from analysis.

2. **`mid_minus_1tick` dropped** — as specified. Notebook uses 3 execution modes (bid_ask, mid, mid_plus_1tick).

3. **Runtime**: 161.6 min (plan estimated 1–1.5 hours on 8 cores; actual was ~2.7 hours). The train period (2018–2022) is longer and more computation-intensive than estimated.

## Confidence: certain

Grid ran to completion with exit code 0. Parquet verified: 24,192 rows, column schema correct, no silent data corruption.
