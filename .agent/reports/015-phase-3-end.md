# Plan 015 — Phase 3 End Report: Grid Degeneracy Analysis

**Date:** 2026-05-15  
**Commit:** 3356b96  
**Notebook:** `research/2026-05-15 - B3 - v7 refined grid.ipynb` (Cell L added at end)

## Step 3.1: Degeneracy Quantification

Grouped the v7 grid by `(target_delta, dte_max, profit_target_pct, vix_filter, execution_mode, period_label)` and counted unique result vectors across the 8 `manage_at_dte × stop_loss_pct` combinations.

**Result:**
- Total grid groups: **768**
- Degenerate groups (≥2 combos produce identical results): **50 (6.5%)**
- Non-degenerate groups: **718 (93.5%)**

Degeneracy is concentrated in `mid_plus_1tick` at tight profit targets (25%), where all trades exit at PROFIT before reaching the minimum `manage_at_dte` threshold (5 days). The `bid_ask` mode has zero degenerate groups because spread-based fills produce more varied P&L.

**Canonical example confirmed:**
```
12δ/dte30/pt25%/rv_pct:80/mid_plus_1tick/holdout:
  6 rows all show: Sharpe=11.557057, n=90, total_return=0.04472, mdd=-0.000691
  manage_at_dte ∈ {5, 7, 14} × stop_loss_pct ∈ {2.0, 3.0}
```

## Step 3.2: Cell L Added

Appended two cells to the v7 notebook (`a6e04c24` → `cb688f5e` markdown → `132f74c1` code):
- **Markdown cell** explains the degeneracy mechanism and gives the canonical example
- **Code cell** quantifies degeneracy across the full grid, prints top degenerate groups, and reproduces the 6 identical Sharpe rows

## Key Finding

Degeneracy occurs when `profit_target_pct` is tight relative to `dte_max` and `target_delta`, making trades exit so quickly that `manage_at_dte` and `stop_loss_pct` never activate. This is a structural property of the strategy, not a bug. It explains why 6 rows appear identical in the v7 Cell J top-5 for `mid_plus_1tick`.

## Confidence

**Certain** — Deterministic analysis from grid results. No sampling or estimation involved.
